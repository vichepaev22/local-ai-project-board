"""Bounded local Hermes CLI bridge for the project board.

The bridge intentionally uses Hermes' configured provider, tools, approval policy,
and credentials.  It does not turn those permissions into a Codex sandbox and it
never adds Hermes' approval-bypass flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from typing import Any


_DEFAULT_TIMEOUT = 300
_MAX_TIMEOUT = 3600
_DEFAULT_MAX_TURNS = 20
_MAX_TURNS = 500
_MAX_CLI_VALUE = 240


class HermesBridgeError(RuntimeError):
    """A safe error that may be persisted and shown by the board."""


@dataclass(frozen=True)
class _Settings:
    executable: str
    model: str | None
    provider: str | None
    timeout: int
    max_turns: int


def _optional_cli_value(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    if (
        not value
        or len(value) > _MAX_CLI_VALUE
        or any(character in value for character in "\r\n\x00")
        or value.startswith("-")
    ):
        raise HermesBridgeError(f"Параметр {name} задан неверно.")
    return value


def _bounded_integer(name: str, default: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise HermesBridgeError(f"Параметр {name} должен быть целым числом.") from error
    if not 1 <= value <= maximum:
        raise HermesBridgeError(f"Параметр {name} должен быть от 1 до {maximum}.")
    return value


def _resolve_executable() -> str:
    override = os.environ.get("PROJECT_BOARD_HERMES_BIN")
    if override is not None:
        candidate = Path(override.strip())
        if not candidate.is_absolute() or not candidate.is_file():
            raise HermesBridgeError(
                "PROJECT_BOARD_HERMES_BIN должен содержать абсолютный путь к файлу Hermes CLI."
            )
        return str(candidate.resolve())
    discovered = shutil.which("hermes")
    if not discovered:
        raise HermesBridgeError(
            "Hermes CLI не найден в PATH. Укажите абсолютный путь в PROJECT_BOARD_HERMES_BIN."
        )
    candidate = Path(discovered)
    if not candidate.is_file():
        raise HermesBridgeError("Hermes CLI из PATH не является доступным файлом.")
    return str(candidate.resolve())


def _load_settings() -> _Settings:
    return _Settings(
        executable=_resolve_executable(),
        model=_optional_cli_value("PROJECT_BOARD_HERMES_MODEL"),
        provider=_optional_cli_value("PROJECT_BOARD_HERMES_PROVIDER"),
        timeout=_bounded_integer("PROJECT_BOARD_HERMES_TIMEOUT", _DEFAULT_TIMEOUT, _MAX_TIMEOUT),
        max_turns=_bounded_integer("PROJECT_BOARD_HERMES_MAX_TURNS", _DEFAULT_MAX_TURNS, _MAX_TURNS),
    )


class HermesBridge:
    """Run one non-interactive Hermes process for a confirmed project batch."""

    kind = "hermes"

    def __init__(self) -> None:
        self._settings: _Settings | None = None
        self._configuration_error: str | None = None
        try:
            self._settings = _load_settings()
        except HermesBridgeError as error:
            self._configuration_error = str(error)
        self._locks_guard = threading.Lock()
        self._project_locks: dict[str, threading.Lock] = {}
        self._active_queue_ids: set[str] = set()
        self._processes: dict[int, tuple[Any, list[dict[str, Any]]]] = {}
        self._closing = False
        self._recovery_guard = threading.Lock()
        self._recovery_done = False
        # Server timestamps intentionally have second precision.  A queue event
        # from this second or later may have been claimed after this bridge was
        # constructed, so startup recovery must leave it to the live worker.
        self._startup_at = datetime.now(timezone.utc).replace(microsecond=0)

    @property
    def online(self) -> bool:
        return self._settings is not None and self._configuration_error is None and not self._closing

    def close(self) -> None:
        """Stop only owned children; no late worker may publish a successful result."""
        with self._locks_guard:
            self._closing = True
            owned = list(self._processes.values())
        for process, items in owned:
            self._kill_owned_process(process, drain=False)
            self._interrupt(items)

    @staticmethod
    def _interrupt(items: list[dict[str, Any]]) -> None:
        import server
        with server.DATA_LOCK:
            for item in items:
                current = server.find_queue_item(str(item['id']))
                if current and current.get('status') in server.ACTIVE_STATUSES:
                    server.update_queue_item(str(item['id']),status='interrupted',progress=100,
                        progressStage='Доска остановлена; процесс Hermes завершён',
                        error='Остановка доски прервала запуск. Автоматический повтор не выполнялся.')

    def snapshot(self) -> dict[str, Any]:
        if self.online:
            message = (
                "Hermes CLI готов к запуску после подтверждения. Hermes работает с вашими "
                "настроенными правами и правилами одобрения; это не песочница Codex."
            )
        else:
            message = self._configuration_error or "Hermes CLI недоступен."
        return {
            "enabled": True,
            "online": self.online,
            "kind": self.kind,
            "message": message,
        }

    def available_models(self) -> list[dict[str, Any]]:
        if not self.online or self._settings is None:
            return []
        if not self._settings.model:
            return []
        return [{
            "id": self._settings.model,
            "label": self._settings.model,
            "isDefault": True,
        }]

    def current_budget(self) -> dict[str, Any]:
        # Imported lazily so server.py can select this bridge without a circular import.
        import server

        return {
            "limitEnforced": False,
            "dispatchAllowed": self.online,
            "isLive": False,
            "capturedAt": server.now(),
            "note": (
                "Hermes не предоставляет борду достоверные окна лимитов; доступность проверяется "
                "только по локальному CLI."
            ),
            "fiveHour": {"remainingPercent": None, "resetsAt": None},
            "weekly": {"remainingPercent": None, "resetsAt": None},
        }

    def schedule_reconciliation(self, queue: list[dict[str, Any]]) -> None:
        """Mark jobs left active by a prior process as interrupted, never rerun them."""
        with self._recovery_guard:
            if self._recovery_done:
                return
            self._recovery_done = True
            with self._locks_guard:
                active_here = set(self._active_queue_ids)

        import server

        for item in queue:
            queue_id = str(item.get("id") or "")
            if (
                not queue_id
                or queue_id in active_here
                or item.get("status") not in server.ACTIVE_STATUSES
                or self._claimed_after_startup(item)
            ):
                continue
            server.update_queue_item(
                queue_id,
                status="interrupted",
                progress=100,
                progressStage="Потеряна связь с предыдущим запуском Hermes",
                error=(
                    "Локальный процесс Hermes больше не связан с бордом. "
                    "Автоматический повтор не выполнялся. Перед повтором убедитесь, что предыдущий Hermes и его инструменты завершены."
                ),
            )
            server.record_event("turn_interrupted", queue_id=queue_id)

    def dispatch(self, queue_id: str) -> None:
        self.dispatch_many([queue_id])

    def dispatch_many(self, queue_ids: list[str]) -> None:
        import server

        items = [server.find_queue_item(queue_id) for queue_id in queue_ids]
        items = [item for item in items if item and item.get("status") == "dispatching"]
        if not items:
            return

        project_id = str(items[0].get("projectId") or "")
        if not project_id or any(str(item.get("projectId") or "") != project_id for item in items):
            self._fail(items, "В одном запуске Hermes могут быть только запросы одного проекта.")
            return

        project_lock = self._project_lock(project_id)
        if not project_lock.acquire(blocking=False):
            message = "В этом проекте уже работает Hermes. Повторите отправку после его завершения."
            for item in items:
                queue_id = str(item["id"])
                server.update_queue_item(
                    queue_id,
                    status="waiting-busy",
                    progress=15,
                    progressStage="Hermes уже занят этим проектом",
                    error=message,
                )
                server.record_event("task_dispatch_failed", queue_id=queue_id, detail=message)
            return

        item_ids = {str(item["id"]) for item in items}
        with self._locks_guard:
            self._active_queue_ids.update(item_ids)
        try:
            # If no state request ran before a direct API confirmation, recover
            # older jobs now.  The current IDs are already tracked and skipped.
            self.schedule_reconciliation(server.read_json(server.QUEUE_FILE))
            self._dispatch_locked(project_id, items)
        finally:
            with self._locks_guard:
                self._active_queue_ids.difference_update(item_ids)
            project_lock.release()

    def _project_lock(self, project_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._project_locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._project_locks[project_id] = lock
            return lock

    def _dispatch_locked(self, project_id: str, items: list[dict[str, Any]]) -> None:
        import server

        project = server.project_by_id(project_id)
        if project is None:
            self._fail(items, "Карточка проекта больше не существует.")
            return
        if not self.online or self._settings is None:
            self._fail(items, self._configuration_error or "Hermes CLI недоступен.")
            return

        workspace_value = project.get("workspace")
        workspace = Path(str(workspace_value or ""))
        if not workspace.is_absolute() or not workspace.is_dir():
            self._fail(items, "Для запуска Hermes укажите существующую абсолютную рабочую папку проекта.")
            return
        workspace = workspace.resolve()

        try:
            selected = server.selected_model(items)
        except Exception:
            self._fail(items, "Запросы одного пакета должны использовать одну модель Hermes.")
            return
        if selected and selected != self._settings.model:
            self._fail(items, "Выбранная модель не совпадает с PROJECT_BOARD_HERMES_MODEL; автозамены не было.")
            return
        model = selected or self._settings.model

        old_route = project.get("route") if isinstance(project.get("route"), dict) else {}
        resume_id = None
        if old_route.get("harness") == "hermes" and isinstance(old_route.get("sessionId"), str):
            try:
                resume_id = self._validated_session_id(old_route["sessionId"])
            except HermesBridgeError:
                self._fail(items, "Сохранённый идентификатор сессии Hermes неверен. Автоматический повтор отменён.")
                return

        label = f"Hermes · {project.get('name', project_id)}"
        pending_route = {
            "status": "linked" if resume_id else "auto-create",
            "label": label,
            "harness": "hermes",
            "sessionId": resume_id,
        }
        server.set_project_route(project_id, pending_route)
        command = self._command(workspace, model=model, resume_id=resume_id)
        prompt = server.CodexBridge._build_prompt(project, items)

        process: subprocess.Popen[str] | None = None
        try:
            process_options: dict[str, Any] = {
                "cwd": str(workspace),
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "shell": False,
            }
            if os.name == "nt":
                process_options["creationflags"] = (
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
            else:
                process_options["start_new_session"] = True
            with self._locks_guard:
                if self._closing:
                    self._interrupt(items)
                    return
                process = subprocess.Popen(command, **process_options)
                self._processes[id(process)] = (process, items)
                started_at = server.now()
                for item in items:
                    queue_id = str(item["id"])
                    server.update_queue_item(queue_id,status="running",progress=30,
                        progressStage="Hermes CLI запущен; ожидаем терминальный результат",
                        route=pending_route,startedAt=started_at)
                    server.record_event("task_dispatched", queue_id=queue_id)
            server.append_activity("dispatch", f"Передано в Hermes: {project.get('name', project_id)} ({len(items)} правок).")
            try:
                stdout, _stderr = self._collect(process, prompt, self._settings.timeout)
            except subprocess.TimeoutExpired as error:
                self._kill_owned_process(process,drain=not hasattr(getattr(process,'stdout',None),'read'))
                raise HermesBridgeError(
                    f"Hermes превысил лимит времени {self._settings.timeout} секунд и был остановлен."
                ) from error

            result = self._parse_result(stdout, process.returncode)
            session_id = self._validated_session_id(result["sessionId"])
            route = {
                "status": "linked",
                "label": label,
                "harness": "hermes",
                "sessionId": session_id,
            }
            with self._locks_guard:
                if self._closing:
                    self._interrupt(items)
                    return
                server.set_project_route(project_id, route)
                stamp = server.now()
                for item in items:
                    queue_id = str(item["id"])
                    server.update_queue_item(queue_id,status="completed",progress=100,
                        progressStage="Результат Hermes готов",route=route,completedAt=stamp,
                        result=result["text"],answerText=result["text"],answerUpdatedAt=stamp,error=None)
                    server.record_event("turn_completed", queue_id=queue_id)
            server.append_activity("result", f"Готов результат Hermes: {project.get('name', project_id)}.")
        except HermesBridgeError as error:
            if self._closing: self._interrupt(items)
            else: self._fail(items, str(error))
        except (OSError, ValueError):
            if self._closing: self._interrupt(items)
            else: self._fail(items, "Не удалось запустить Hermes CLI или прочитать его структурированный ответ.")
        except Exception:
            # Do not persist exception text: transport/provider errors may contain
            # request bodies, local paths, credential names, or other secrets.
            if self._closing: self._interrupt(items)
            else: self._fail(items, "Hermes CLI завершился с неожиданной локальной ошибкой.")
        finally:
            if process is not None:
                with self._locks_guard:
                    self._processes.pop(id(process),None)

    @staticmethod
    def _collect(process: subprocess.Popen[str], prompt: str, timeout: int) -> tuple[str,str]:
        # Transport doubles need only communicate(); real pipes are drained with
        # bounded buffers. Tool output must not exhaust memory before a timeout.
        if not hasattr(getattr(process,'stdout',None),'read'):
            return process.communicate(input=prompt,timeout=timeout)
        chunks: list[str] = []
        overflow, transport_error = threading.Event(), threading.Event()
        def drain(pipe: Any, keep: bool, maximum: int) -> None:
            count=0
            try:
                while True:
                    chunk=pipe.read(4096)
                    if not chunk: break
                    count += len(chunk)
                    if count > maximum:
                        overflow.set()
                        return
                    if keep: chunks.append(chunk)
            except (OSError,ValueError): transport_error.set()
            finally:
                pipe.close()
        def write_prompt() -> None:
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except (OSError,ValueError): transport_error.set()
        readers=[threading.Thread(target=drain,args=(process.stdout,True,2_000_000),daemon=True),
                 threading.Thread(target=drain,args=(process.stderr,False,200_000),daemon=True)]
        writer=threading.Thread(target=write_prompt,daemon=True)
        for thread in [*readers,writer]: thread.start()
        deadline=time.monotonic()+timeout
        while process.poll() is None:
            if overflow.is_set():
                HermesBridge._kill_owned_process(process,drain=False)
                raise HermesBridgeError('Вывод Hermes превысил безопасный размер; запуск остановлен.')
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('hermes',timeout)
            time.sleep(0.05)
        for thread in [*readers,writer]: thread.join(timeout=1)
        if overflow.is_set():
            raise HermesBridgeError('Вывод Hermes превысил безопасный размер; результат не принят.')
        if transport_error.is_set() or any(thread.is_alive() for thread in [*readers,writer]):
            raise HermesBridgeError('Не удалось завершить чтение ответа Hermes; результат не принят.')
        return ''.join(chunks), ''

    def _command(self, workspace: Path, *, model: str | None, resume_id: str | None) -> list[str]:
        assert self._settings is not None
        command = [
            self._settings.executable,
            "chat",
            "--query-file", "-",
            "--format", "stream-json",
            "--max-turns", str(self._settings.max_turns),
            "--run-budget", str(self._settings.timeout),
            "--in", str(workspace),
            "--no-restore-cwd",
        ]
        if resume_id:
            command.extend(["--resume", resume_id])
        if model:
            command.extend(["-m", model])
        if self._settings.provider:
            command.extend(["--provider", self._settings.provider])
        return command

    def _claimed_after_startup(self, item: dict[str, Any]) -> bool:
        raw = item.get("lastEventAt") or item.get("startedAt")
        if not isinstance(raw, str):
            return False
        try:
            stamp = datetime.fromisoformat(raw)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp.astimezone(timezone.utc) >= self._startup_at
        except ValueError:
            return False

    @staticmethod
    def _kill_owned_process(process: subprocess.Popen[str], *, drain: bool = True) -> None:
        """Terminate only this run's process tree and never wait forever for pipes.

        Hermes tools can start children that inherit stdout/stderr.  Killing only
        the parent and then calling an unbounded ``communicate`` can therefore
        hang the board.  The PID/process group was created by this bridge, so the
        tree-scoped termination does not select unrelated names or processes.
        """
        pid = getattr(process, "pid", None)
        if isinstance(pid,int) and process.poll() is not None:
            return
        terminated = False
        if isinstance(pid, int) and pid > 0:
            if os.name == "nt":
                try:
                    completed = subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                        shell=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    terminated = completed.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass
            else:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    terminated = True
                except (OSError, ProcessLookupError):
                    pass
        if not terminated:
            try:
                process.kill()
            except OSError:
                pass
        if not drain:
            try:
                process.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired,AttributeError):
                pass
            return
        try:
            process.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            # Do not wait again: a surviving tool may still own a copied pipe.
            for pipe_name in ("stdin", "stdout", "stderr"):
                pipe = getattr(process, pipe_name, None)
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        pass

    @staticmethod
    def _validated_session_id(value: Any) -> str:
        if not isinstance(value, str):
            raise HermesBridgeError("Hermes CLI не вернул идентификатор сессии.")
        session_id = value.strip()
        if (
            not session_id
            or len(session_id) > _MAX_CLI_VALUE
            or any(character in session_id for character in "\r\n\x00")
            or session_id.startswith("-")
        ):
            raise HermesBridgeError("Hermes CLI вернул неверный идентификатор сессии.")
        return session_id

    @staticmethod
    def _parse_result(stdout: str, returncode: int | None) -> dict[str, str]:
        terminal: dict[str, Any] | None = None
        init_session = ""
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise HermesBridgeError("Hermes CLI вернул неструктурированный вывод; задача не завершена.") from error
            if not isinstance(event, dict):
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                if isinstance(event.get("session_id"), str):
                    init_session = event["session_id"]
            elif event.get("type") == "result":
                terminal = event
        if terminal is None:
            raise HermesBridgeError("Hermes CLI не вернул терминальное событие result; задача не завершена.")
        event_exit = terminal.get("exit_code")
        if returncode not in (None, 0) or not isinstance(event_exit, int) or event_exit != 0 or terminal.get("error"):
            code = returncode if returncode not in (None, 0) else event_exit
            raise HermesBridgeError(
                f"Hermes CLI завершился с ошибкой провайдера или конфигурации (code {code})."
            )
        text = terminal.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HermesBridgeError("Hermes CLI завершился без итогового текста; пустой ответ не считается успехом.")
        session_id = terminal.get("session_id") or init_session
        return {"text": text.strip(), "sessionId": session_id}

    @staticmethod
    def _fail(items: list[dict[str, Any]], message: str) -> None:
        import server

        for item in items:
            queue_id = str(item["id"])
            server.update_queue_item(
                queue_id,
                status="failed",
                progress=0,
                progressStage="Не удалось выполнить через Hermes",
                error=message,
            )
            server.record_event("task_dispatch_failed", queue_id=queue_id, detail=message)
        project_name = items[0].get("projectName") if items else None
        server.append_activity("error", f"Не выполнена задача Hermes{f': {project_name}' if project_name else ''}.")


__all__ = ["HermesBridge", "HermesBridgeError"]
