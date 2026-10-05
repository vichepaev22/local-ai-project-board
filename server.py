"""Local project dashboard with a live, local-only Codex App Server bridge."""

from __future__ import annotations

import copy
import json
import logging
import mimetypes
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from board import BoardConflict, apply_operation, normalize_board
from codex_runtime import resolve_runtime, RuntimeSelectionError
from runtime_data import initialize_data


ROOT = Path(__file__).resolve().parent
_configured_data_dir = os.environ.get("PROJECT_BOARD_DATA_DIR")
_runtime_paths = initialize_data(Path(_configured_data_dir) if _configured_data_dir else ROOT / "data")
DATA = _runtime_paths["DATA"]
PROJECTS_FILE = _runtime_paths["PROJECTS_FILE"]
BUDGET_FILE = _runtime_paths["BUDGET_FILE"]
QUEUE_FILE = _runtime_paths["QUEUE_FILE"]
ACTIVITY_FILE = _runtime_paths["ACTIVITY_FILE"]
EVENTS_FILE = _runtime_paths["EVENTS_FILE"]
TOMORROW_FILE = _runtime_paths["TOMORROW_FILE"]
BOARD_FILE = _runtime_paths["BOARD_FILE"]
DATA_LOCK = threading.RLock()
LOG = logging.getLogger("portfolio_dashboard")
TERMINAL_STATUSES = {"completed", "failed", "interrupted", "blocked-external-access"}
ACTIVE_STATUSES = {"dispatching", "running", "waiting-user", "waiting-busy"}
PUBLIC_ASSETS = {
    "app.js", "attention-view.js", "attention.css", "attention.js", "board-drag.js",
    "board-ui.js", "board.css", "board.html", "demo.css", "demo.html", "demo.js",
    "execution-status.js", "execution-view.js", "execution.css", "favicon.svg",
    "harness-mode.js", "motion-events.js", "motion.css", "motion.js", "project-detail.js",
    "project-history.js", "pulse-ui.js", "pulse.css", "queue-journal-ui.js",
    "queue-journal.css", "queue-journal.js", "task-models.js",
}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def bridge_kind(bridge: Any | None = None) -> str:
    """Treat old test doubles without a kind as the original Codex bridge."""
    value = getattr(bridge or BRIDGE, "kind", "codex")
    return value if isinstance(value, str) else "codex"


def is_codex_bridge(bridge: Any | None = None) -> bool:
    return bridge_kind(bridge) == "codex"


def validated_workspace(value: Any) -> str:
    """Return an explicit usable workspace or a displayable validation failure."""
    if not isinstance(value, str) or not value.strip():
        raise AppServerError("Для автоматического запуска укажите существующую абсолютную рабочую папку проекта.")
    workspace = Path(value.strip())
    if not workspace.is_absolute() or not workspace.is_dir():
        raise AppServerError("Рабочая папка должна быть существующей абсолютной папкой.")
    return str(workspace.resolve())


def workspace_for_planning(value: Any) -> str:
    """Empty workspace is valid while planning, but non-empty values must be safe."""
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError("Рабочая папка должна быть строкой.")
    try:
        return validated_workspace(value)
    except AppServerError as error:
        raise ValueError(str(error)) from error


def read_json(path: Path) -> Any:
    with DATA_LOCK, path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, value: Any) -> None:
    with DATA_LOCK:
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(path)


def append_activity(event_type: str, text: str) -> None:
    with DATA_LOCK:
        items = read_json(ACTIVITY_FILE)
        items.insert(0, {"at": now(), "type": event_type, "text": text[:800]})
        write_json(ACTIVITY_FILE, items[:60])


def record_event(event_type: str, *, queue_id: str | None = None, detail: str | None = None) -> None:
    """Store diagnostics without prompts, secrets, or full model output."""
    event: dict[str, str] = {"at": now(), "event": event_type}
    if queue_id:
        event["queueId"] = queue_id
    if detail:
        event["detail"] = detail[:500]
    with DATA_LOCK, EVENTS_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")


def find_queue_item(queue_id: str) -> dict[str, Any] | None:
    for item in read_json(QUEUE_FILE):
        if item.get("id") == queue_id:
            return copy.deepcopy(item)
    return None


def update_queue_item(queue_id: str, **changes: Any) -> dict[str, Any] | None:
    with DATA_LOCK:
        queue = read_json(QUEUE_FILE)
        for item in queue:
            if item.get("id") != queue_id:
                continue
            if changes.get("status") and changes["status"] != item.get("status"):
                item.setdefault("history", []).append({"at": now(), "status": changes["status"], "text": changes.get("progressStage", "")})
            item.update(changes)
            item["lastEventAt"] = now()
            write_json(QUEUE_FILE, queue)
            return copy.deepcopy(item)
    return None


def matching_queue_ids(thread_id: str, turn_id: str | None = None) -> list[str]:
    matches: list[str] = []
    for item in read_json(QUEUE_FILE):
        route = item.get("route", {})
        # A Hermes session identifier must never be mistaken for a Codex thread.
        if isinstance(route, dict) and route.get("harness") == "hermes":
            continue
        if route.get("threadId") != thread_id or item.get("status") not in ACTIVE_STATUSES:
            continue
        stored_turn_id = item.get("turnId")
        if turn_id and stored_turn_id and stored_turn_id != turn_id:
            continue
        matches.append(str(item["id"]))
    return matches


def set_project_route(project_id: str, route: dict[str, Any]) -> None:
    """Persist one route on the project and every pending item for that project."""
    with DATA_LOCK:
        projects = read_json(PROJECTS_FILE)
        for project in projects:
            if project.get("id") == project_id:
                project["route"] = route
                break
        write_json(PROJECTS_FILE, projects)
        queue = read_json(QUEUE_FILE)
        for item in queue:
            if (item.get("projectId") == project_id
                    and item.get("status") in {"queued", *ACTIVE_STATUSES}
                    and not item.get("archivedAt")):
                item["route"] = route
        write_json(QUEUE_FILE, queue)


def project_by_id(project_id: str) -> dict[str, Any] | None:
    for project in read_json(PROJECTS_FILE):
        if project.get("id") == project_id:
            return copy.deepcopy(project)
    return None


def queue_capacity(budget: dict[str, Any] | None = None) -> int:
    budget = budget or read_json(BUDGET_FILE)
    return max(1, min(int(budget["fiveHour"]["remainingPercent"]), int(budget["weekly"]["remainingPercent"])))


def scope_points(scope: str) -> int:
    return {"small": 4, "normal": 11, "deep": 24}.get(scope, 11)


def group_queue_items(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """One Codex turn per project prevents competing turns in one linked chat."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = str(item.get("projectId") or item.get("id"))
        grouped.setdefault(key, []).append(item)
    return list(grouped.values())


def dispatch_points(items: list[dict[str, Any]]) -> int:
    """Related changes in one project share one coordinated Codex turn."""
    return sum(max(scope_points(str(item.get("scope"))) for item in group) for group in group_queue_items(items))


def selected_model(items: list[dict[str, Any]]) -> str | None:
    choices = {item.get("model") or None for item in items}
    if len(choices) > 1:
        raise AppServerError("У поручений одного проекта выбраны разные модели. Отметьте в журнале поручения с одной моделью и отправьте их отдельно.")
    return next(iter(choices), None)


def item_is_stale(item: dict[str, Any]) -> bool:
    if item.get("status") not in ACTIVE_STATUSES:
        return False
    raw = item.get("lastEventAt") or item.get("startedAt")
    if not isinstance(raw, str):
        return False
    try:
        elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(raw).astimezone(timezone.utc)
    except ValueError:
        return False
    return elapsed.total_seconds() > 120


@dataclass
class PendingCall:
    event: threading.Event
    result: dict[str, Any] | None = None
    error: str | None = None


class AppServerError(RuntimeError):
    """A safe, user-displayable failure from the local Codex bridge."""


class CodexBridge:
    """JSON-RPC client that keeps Codex progress attached to dashboard tasks."""

    kind = "codex"

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.runtime: dict[str, str] | None = None
        self._next_id = 1
        self._pending: dict[int, PendingCall] = {}
        self._pending_lock = threading.RLock()
        self._write_lock = threading.Lock()
        # start() invokes the JSON-RPC initializer, which uses request().
        # A re-entrant lock prevents that first initialization request from
        # waiting on the lock it already owns.
        self._start_lock = threading.RLock()
        self._route_lock = threading.Lock()
        self._budget_lock = threading.Lock()
        self._models_lock = threading.Lock()
        self._models: list[dict[str, Any]] = []
        self._models_at = 0.0
        self._reconcile_lock = threading.Lock()
        self._reconcile_running = False
        self._last_reconcile_at = 0.0

    @property
    def online(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def snapshot(self) -> dict[str, Any]:
        if self.online:
            version = self.runtime['version'] if self.runtime else 'неизвестной версии'
            return {"kind": self.kind, "enabled": True, "online": True, "runtime": self.runtime, "message": f"Codex {version} подключён и слушает ход задач. Старые ошибки не означают повторный запуск."}
        return {"kind": self.kind, "enabled": True, "online": False, "message": "Bridge запустится автоматически при подтверждении очереди."}

    def start(self) -> None:
        with self._start_lock:
            if self.online:
                return
            try:
                self.runtime = resolve_runtime()
            except RuntimeSelectionError as error:
                raise AppServerError(str(error)) from error
            codex_bin = self.runtime['executable']
            self.process = subprocess.Popen(
                [codex_bin, "app-server", "--stdio"],
                cwd=str(ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            threading.Thread(target=self._read_stdout, name="portfolio-codex-reader", daemon=True).start()
            threading.Thread(target=self._read_stderr, name="portfolio-codex-stderr", daemon=True).start()
            self.request(
                "initialize",
                {
                    "clientInfo": {"name": "project-portfolio-dashboard", "version": "2.0"},
                    "capabilities": {"experimentalApi": True},
                },
                timeout=30,
            )
            self.notify("initialized", {})
            record_event("bridge_started", detail=f"Codex {self.runtime['version']}: {codex_bin}")

    def request(self, method: str, params: dict[str, Any] | None, *, timeout: int = 45) -> dict[str, Any]:
        self.start()
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            pending = PendingCall(event=threading.Event())
            self._pending[request_id] = pending
        try:
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            if not pending.event.wait(timeout):
                raise AppServerError("Codex bridge не подтвердил действие вовремя. Задача не отправлена повторно.")
            if pending.error:
                raise AppServerError(pending.error)
            return pending.result or {}
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def available_models(self) -> list[dict[str, Any]]:
        """Read the installed runtime's catalog, never launch a turn. Cache for 60s."""
        with self._models_lock:
            if self._models and time.monotonic() - self._models_at < 60:
                return copy.deepcopy(self._models)
            models: dict[str, dict[str, Any]] = {}
            cursor = None
            seen = set()
            while True:
                params: dict[str, Any] = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor
                result = self.request("model/list", params, timeout=15)
                data = result.get("data") if isinstance(result, dict) else None
                if not isinstance(data, list):
                    raise AppServerError("Codex вернул некорректный список моделей. Повторите обновление.")
                for item in data:
                    if not isinstance(item, dict):
                        raise AppServerError("Codex вернул некорректный список моделей. Повторите обновление.")
                    model = item.get("model")
                    if not isinstance(model, str) or not model or item.get("hidden"):
                        continue
                    supported = item.get("supportedReasoningEfforts")
                    if not isinstance(supported, list) or not all(isinstance(effort, str) for effort in supported):
                        supported = []
                    default_effort = item.get("defaultReasoningEffort")
                    models[model] = {
                        "id": model,
                        "label": item.get("displayName") or model,
                        "isDefault": bool(item.get("isDefault")),
                        "supportedReasoningEfforts": supported,
                        "defaultReasoningEffort": default_effort if isinstance(default_effort, str) else None,
                    }
                cursor = result.get("nextCursor")
                if cursor is not None and not isinstance(cursor, str):
                    raise AppServerError("Codex вернул некорректный список моделей. Повторите обновление.")
                if not cursor:
                    break
                if cursor in seen:
                    raise AppServerError("Codex вернул неполный список моделей. Повторите обновление.")
                seen.add(cursor)
            if not models:
                raise AppServerError("Codex не вернул доступные модели. Можно оставить модель связанной задачи.")
            self._models, self._models_at = list(models.values()), time.monotonic()
            return copy.deepcopy(self._models)

    @staticmethod
    def _normalize_budget(response: dict[str, Any]) -> dict[str, Any]:
        snapshots = response.get("rateLimitsByLimitId")
        if not isinstance(snapshots, dict):
            snapshots = {}
        snapshot = snapshots.get("codex") or response.get("rateLimits")
        if not isinstance(snapshot, dict):
            raise AppServerError("Codex не вернул текущие лимиты аккаунта.")

        def window(value: Any) -> dict[str, Any]:
            if not isinstance(value, dict) or not isinstance(value.get("usedPercent"), int):
                raise AppServerError("Codex вернул неполные данные лимита.")
            used = max(0, min(100, int(value["usedPercent"])))
            resets_at = value.get("resetsAt")
            return {
                "remainingPercent": 100 - used,
                "usedPercent": used,
                "resetsAt": resets_at if isinstance(resets_at, int) else None,
                "windowDurationMins": value.get("windowDurationMins"),
            }

        return {
            "capturedAt": now(),
            "source": "Текущие лимиты локального Codex",
            "limitEnforced": True,
            "isLive": True,
            "fiveHour": window(snapshot.get("primary")),
            "weekly": window(snapshot.get("secondary")),
            "note": "Обновляется из текущего аккаунта Codex. Проценты показывают доступную долю лимита.",
        }

    def current_budget(self) -> dict[str, Any]:
        """Read the current account limits; never reuse an old response as live data."""
        with self._budget_lock:
            try:
                budget = self._normalize_budget(self.request("account/rateLimits/read", None, timeout=3))
            except AppServerError as error:
                fallback = copy.deepcopy(read_json(BUDGET_FILE))
                fallback.update(
                    {
                        "isLive": False,
                        "source": "Последний сохранённый снимок — связь с Codex недоступна",
                        "error": str(error)[:300],
                    }
                )
                return fallback
            return budget

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _write(self, payload: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.poll() is not None or process.stdin is None:
            raise AppServerError("Локальный Codex bridge недоступен.")
        with self._write_lock:
            process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for raw_line in process.stdout:
                try:
                    message = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                self._handle_message(message)
        except Exception as error:  # pragma: no cover - defensive bridge boundary
            LOG.exception("Codex bridge reader failed: %s", error)
        finally:
            with self._pending_lock:
                for pending in self._pending.values():
                    pending.error = "Соединение с локальным Codex bridge закрыто."
                    pending.event.set()
            record_event("bridge_closed")

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for raw_line in process.stderr:
            line = raw_line.strip()
            if line:
                LOG.info("codex app-server: %s", line[:500])

    def _handle_message(self, message: dict[str, Any]) -> None:
        if "id" in message and "method" not in message:
            with self._pending_lock:
                pending = self._pending.get(message["id"])
            if pending is None:
                return
            error = message.get("error")
            if isinstance(error, dict):
                pending.error = str(error.get("message") or "Codex отклонил действие.")
            elif error:
                pending.error = "Codex отклонил действие."
            else:
                result = message.get("result", {})
                pending.result = result if isinstance(result, dict) else {}
            pending.event.set()
            return

        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        if "id" in message:
            self._handle_server_request(message["id"], method, params)
        else:
            self._handle_event(method, params)

    def _handle_server_request(self, request_id: int | str, method: str, params: dict[str, Any]) -> None:
        thread_id = params.get("threadId")
        if isinstance(thread_id, str) and method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
            "tool/requestUserInput",
        }:
            for queue_id in matching_queue_ids(thread_id):
                item = find_queue_item(queue_id) or {}
                update_queue_item(
                    queue_id,
                    status="waiting-user",
                    progress=max(70, int(item.get("progress", 0))),
                    progressStage="Нужно ваше решение в Codex",
                    waitingFor=method,
                )
                record_event("task_waiting_user", queue_id=queue_id, detail=method)
            append_activity("attention", "Задача Codex ждёт вашего решения; дашборд не даёт разрешений автоматически.")
            return
        # Unknown interactive requests are declined instead of silently granting access.
        self.respond(request_id, {})

    def _handle_event(self, method: str, params: dict[str, Any]) -> None:
        thread_id = params.get("threadId")
        if not isinstance(thread_id, str):
            return
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        if method == "turn/completed":
            self._apply_terminal_turn(thread_id, turn)
            return
        raw_turn_id = turn.get("id") if isinstance(turn.get("id"), str) else params.get("turnId")
        turn_id = raw_turn_id if isinstance(raw_turn_id, str) else None
        queue_ids = matching_queue_ids(thread_id, turn_id)
        if not queue_ids:
            return

        if method == "turn/started":
            for queue_id in queue_ids:
                update_queue_item(queue_id, status="running", progress=30, progressStage="Codex принял задачу", turnId=turn_id, startedAt=now())
                record_event("turn_started", queue_id=queue_id)
            return

        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            for queue_id in queue_ids:
                item = find_queue_item(queue_id) or {}
                update_queue_item(
                    queue_id,
                    status="running",
                    progress=max(55, int(item.get("progress", 30))),
                    progressStage="Codex работает",
                    lastMessage=str(delta or item.get("lastMessage", ""))[-600:],
                )
            return

        if method == "item/completed":
            item = params.get("item")
            if not isinstance(item, dict) or item.get("type") != "agentMessage":
                return
            text = self._item_text(item)
            if not text:
                return
            for queue_id in queue_ids:
                update_queue_item(queue_id, progress=85, progressStage="Codex формирует итог", lastMessage=text[-4000:])
            return

        if method == "thread/status/changed":
            status = params.get("status") if isinstance(params.get("status"), dict) else {}
            flags = status.get("activeFlags") if isinstance(status.get("activeFlags"), list) else []
            if flags:
                for queue_id in queue_ids:
                    update_queue_item(queue_id, status="waiting-user", progress=70, progressStage="Нужно ваше решение в Codex", waitingFor=", ".join(map(str, flags)))

    def _apply_terminal_turn(self, thread_id: str, turn: dict[str, Any]) -> None:
        """Persist a terminal turn state from either a live event or a later reconciliation."""
        turn_id = turn.get("id") if isinstance(turn.get("id"), str) else None
        queue_ids = matching_queue_ids(thread_id, turn_id)
        if not queue_ids:
            return
        status = str(turn.get("status", "failed"))
        error = turn.get("error") if isinstance(turn.get("error"), dict) else {}
        for queue_id in queue_ids:
            item = find_queue_item(queue_id) or {}
            if status == "completed":
                update_queue_item(
                    queue_id,
                    status="completed",
                    progress=100,
                    progressStage="Результат готов",
                    completedAt=now(),
                    result=item.get("lastMessage") or "Codex завершил задачу. Откройте связанный диалог для полного ответа.",
                )
                append_activity("result", f"Готов результат: {item.get('projectName', 'проект')}.")
                record_event("turn_completed", queue_id=queue_id)
            elif status == "interrupted":
                update_queue_item(
                    queue_id,
                    status="interrupted",
                    progress=100,
                    progressStage="Задача остановлена — можно повторить пакет",
                    error="Codex прервал запуск до итогового ответа. Повторная отправка доступна и не создаст конкурирующую задачу.",
                )
                record_event("turn_interrupted", queue_id=queue_id)
            else:
                detail = str(error.get("message") or "Codex завершил задачу с ошибкой.")
                update_queue_item(queue_id, status="failed", progress=0, progressStage="Отправка требует внимания", error=detail)
                append_activity("error", f"Нужна проверка задачи: {item.get('projectName', 'проект')}.")
                record_event("turn_failed", queue_id=queue_id, detail=detail)

    def schedule_reconciliation(self, queue: list[dict[str, Any]]) -> None:
        """Reconcile missed terminal events without making the page wait for Codex."""
        candidates = [
            item for item in queue
            if item.get("status") in ACTIVE_STATUSES
            and isinstance(item.get("turnId"), str)
            and isinstance(item.get("route"), dict)
            and isinstance(item["route"].get("threadId"), str)
        ]
        if not candidates:
            return
        with self._reconcile_lock:
            if self._reconcile_running or time.monotonic() - self._last_reconcile_at < 5:
                return
            self._reconcile_running = True
            self._last_reconcile_at = time.monotonic()
        threading.Thread(target=self._reconcile_active_turns, args=(candidates,), name="portfolio-turn-reconcile", daemon=True).start()

    def _reconcile_active_turns(self, candidates: list[dict[str, Any]]) -> None:
        """Ask Codex history for terminal states that arrived while the bridge was unavailable."""
        targets: dict[str, set[str]] = {}
        for item in candidates:
            thread_id = str(item["route"]["threadId"])
            targets.setdefault(thread_id, set()).add(str(item["turnId"]))
        try:
            for thread_id, turn_ids in targets.items():
                response = self.request(
                    "thread/turns/list",
                    {"threadId": thread_id, "limit": 12, "itemsView": "notLoaded"},
                    timeout=6,
                )
                turns = response.get("data") if isinstance(response.get("data"), list) else []
                for turn in turns:
                    if not isinstance(turn, dict) or turn.get("id") not in turn_ids:
                        continue
                    if str(turn.get("status")) in TERMINAL_STATUSES:
                        self._apply_terminal_turn(thread_id, turn)
        except AppServerError as error:
            record_event("turn_reconciliation_failed", detail=str(error))
        finally:
            with self._reconcile_lock:
                self._reconcile_running = False

    @staticmethod
    def _item_text(item: dict[str, Any]) -> str:
        value = item.get("text") or item.get("content") or item.get("message")
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "\n".join(str(part.get("text", "")) for part in value if isinstance(part, dict)).strip()
        return ""

    @staticmethod
    def _model_effort(catalog: list[dict[str, Any]], model: str, current: Any) -> str | None:
        entry = next((candidate for candidate in catalog if candidate.get("id") == model), None)
        if not isinstance(entry, dict):
            return None
        supported = entry.get("supportedReasoningEfforts")
        if not isinstance(supported, list) or not supported:
            return None
        if isinstance(current, str) and current in supported:
            return current
        default = entry.get("defaultReasoningEffort")
        if isinstance(default, str) and default in supported:
            return default
        return supported[0]

    def dispatch(self, queue_id: str) -> None:
        """Compatibility wrapper for one-item retries."""
        self.dispatch_many([queue_id])

    def dispatch_many(self, queue_ids: list[str]) -> None:
        """Send related queue entries to one project as one non-competing Codex turn."""
        items = [find_queue_item(queue_id) for queue_id in queue_ids]
        items = [item for item in items if item and item.get("status") == "dispatching"]
        if not items:
            return
        project_id = str(items[0].get("projectId"))
        if any(str(item.get("projectId")) != project_id for item in items):
            for item in items:
                update_queue_item(str(item["id"]), status="failed", progress=0, progressStage="Некорректная группа", error="В одном запуске могут быть только правки одного проекта.")
            return
        project = project_by_id(project_id)
        if project is None:
            for item in items:
                update_queue_item(str(item["id"]), status="failed", progress=0, progressStage="Проект не найден", error="Карточка проекта больше не существует.")
            return
        try:
            model = selected_model(items)
            catalog = self.available_models() if model else []
            if model and model not in {entry["id"] for entry in catalog}:
                raise AppServerError(f"Модель {model} больше недоступна. Добавьте поручение с доступной моделью; автоматической подмены не было.")
            thread_id, route, current_effort = self._ensure_route(project)
            effort = self._model_effort(catalog, model, current_effort) if model else None
            for item in items:
                update_queue_item(
                    str(item["id"]),
                    route=route,
                    progress=18,
                    progressStage="Сообщение передаётся в Codex" if len(items) == 1 else f"Объединено с {len(items) - 1} связанной правкой",
                )
            turn_params = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": self._build_prompt(project, items)}],
                **({"model": model} if model else {}),
                **({"effort": effort} if effort else {}),
            }
            result = self.request(
                "turn/start",
                turn_params,
                timeout=45,
            )
            turn = result.get("turn") if isinstance(result.get("turn"), dict) else {}
            turn_id = turn.get("id") if isinstance(turn.get("id"), str) else None
            for item in items:
                update_queue_item(str(item["id"]), status="running", progress=30, progressStage="Codex принял задачу", turnId=turn_id, startedAt=now())
                record_event("task_dispatched", queue_id=str(item["id"]))
            append_activity("dispatch", f"Передано в Codex: {project['name']} ({len(items)} правок одним запуском).")
        except AppServerError as error:
            message = str(error)
            status = "waiting-busy" if "active turn" in message.lower() or "steer" in message.lower() else "failed"
            stage = "Диалог занят другой задачей" if status == "waiting-busy" else "Не удалось отправить"
            for item in items:
                update_queue_item(str(item["id"]), status=status, progress=15 if status == "waiting-busy" else 0, progressStage=stage, error=message)
                record_event("task_dispatch_failed", queue_id=str(item["id"]), detail=message)
            append_activity("error", f"Не отправлена задача: {project['name']}.")

    def _ensure_route(self, project: dict[str, Any]) -> tuple[str, dict[str, Any], str | None]:
        with self._route_lock:
            current = project_by_id(str(project["id"])) or project
            route = current.get("route") if isinstance(current.get("route"), dict) else {}
            workspace = validated_workspace(current.get("workspace"))
            thread_id = route.get("threadId")
            if route.get("harness") != "hermes" and isinstance(thread_id, str) and thread_id:
                resumed = self.request("thread/resume", {"threadId": thread_id}, timeout=45)
                current_effort = resumed.get("reasoningEffort") if isinstance(resumed, dict) else None
                return thread_id, route, current_effort if isinstance(current_effort, str) else None
            created = self.request(
                "thread/start",
                {
                    "cwd": workspace,
                    "sandbox": "workspace-write",
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "user",
                    "threadSource": "portfolio-dashboard",
                },
                timeout=45,
            )
            thread = created.get("thread") if isinstance(created.get("thread"), dict) else {}
            thread_id = thread.get("id")
            if not isinstance(thread_id, str) or not thread_id:
                raise AppServerError("Codex не вернул идентификатор нового связанного диалога.")
            label = f"Портфель · {current['name']}"
            self.request("thread/setName", {"threadId": thread_id, "name": label}, timeout=20)
            route = {"status": "linked", "label": label, "harness": "codex", "threadId": thread_id}
            set_project_route(str(current["id"]), route)
            append_activity("route", f"Создан связанный диалог Codex: {current['name']}.")
            record_event("route_created", detail=str(current["id"]))
            current_effort = created.get("reasoningEffort") if isinstance(created, dict) else None
            return thread_id, route, current_effort if isinstance(current_effort, str) else None

    @staticmethod
    def _build_prompt(project: dict[str, Any], items: list[dict[str, Any]]) -> str:
        labels = {"next-step": "ближайший шаг", "goal": "цель проекта", "comment": "комментарий"}
        changes = "\n".join(
            f"{index}. {labels.get(item.get('kind'), 'изменение')}: {item['text']}"
            for index, item in enumerate(items, start=1)
        )
        return (
            f"Задача из дашборда портфеля для проекта «{project['name']}».\n"
            f"Пользователь добавил {len(items)} связан(ных) запрос(а). Обработай их согласованно, но в финале дай отдельный статус по каждому пункту.\n"
            f"Запросы пользователя:\n{changes}\n\n"
            "Работай только в рамках этого запроса. Не публикуй материалы, не отправляй внешние сообщения "
            "и не меняй внешние настройки без отдельного подтверждения. В финале дай краткий проверяемый статус, результат и блокер, если он есть."
        )


class ManualBridge:
    """Planning-only adapter; it intentionally has no executor or quota claim."""

    kind = "manual"
    online = False

    def __init__(self, message: str | None = None) -> None:
        self.message = message or "Ручной режим: запросы можно планировать и копировать, но не отправлять автоматически."

    def snapshot(self) -> dict[str, Any]:
        return {"kind": self.kind, "enabled": True, "online": False, "message": self.message}

    def available_models(self) -> list[dict[str, Any]]:
        return []

    def current_budget(self) -> dict[str, Any]:
        unknown = {"remainingPercent": None, "usedPercent": None, "resetsAt": None, "windowDurationMins": None}
        return {
            "capturedAt": now(),
            "source": "Ручной режим не читает лимиты провайдера",
            "limitEnforced": False,
            "dispatchAllowed": False,
            "isLive": False,
            "fiveHour": copy.deepcopy(unknown),
            "weekly": copy.deepcopy(unknown),
            "note": "Автоматическая отправка отключена; лимиты не заявляются.",
        }

    def schedule_reconciliation(self, queue: list[dict[str, Any]]) -> None:
        return None

    def dispatch_many(self, queue_ids: list[str]) -> None:
        raise AppServerError("Ручной режим не поддерживает автоматическую отправку.")


def create_bridge() -> Any:
    requested = os.environ.get("PROJECT_BOARD_BRIDGE", "manual").strip().lower() or "manual"
    if requested == "codex":
        return CodexBridge()
    if requested == "hermes":
        # Hermes imports this module lazily from its callbacks, avoiding a cycle.
        from hermes_bridge import HermesBridge
        return HermesBridge()
    if requested == "manual":
        return ManualBridge()
    return ManualBridge(f"Неизвестный bridge «{requested}»: автоматическая отправка отключена.")


BRIDGE = create_bridge()


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._head_only = False
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        expected_port = str(self.server.server_port)
        return host in {f"127.0.0.1:{expected_port}", f"localhost:{expected_port}", f"[::1]:{expected_port}"}

    def _valid_write_request(self) -> bool:
        if not self._valid_host():
            self.send_api_error(HTTPStatus.FORBIDDEN, "INVALID_HOST", "Запрос разрешён только с loopback-адреса этого сервера.")
            return False
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self.send_api_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON_REQUIRED", "Для изменения данных нужен application/json.")
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme != "http" or parsed.netloc != self.headers.get("Host"):
                self.send_api_error(HTTPStatus.FORBIDDEN, "INVALID_ORIGIN", "Origin должен совпадать с локальным сервером.")
                return False
        return True

    def _serve_asset(self, path: str) -> None:
        name = "board.html" if path in {"/", "/index.html"} else path.lstrip("/")
        candidate = Path(name)
        if (not name or "/" in name or "\\" in name or name.startswith(".")
                or name not in PUBLIC_ASSETS):
            self.send_api_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Ресурс не найден.")
            return
        unresolved = ROOT / candidate
        target = unresolved.resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            self.send_api_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Ресурс не найден.")
            return
        if unresolved.is_symlink() or not target.is_file():
            self.send_api_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Ресурс не найден.")
            return
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not self._head_only:
            self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_GET(self) -> None:  # noqa: N802
        if not self._valid_host():
            return self.send_api_error(HTTPStatus.FORBIDDEN, "INVALID_HOST", "Запрос разрешён только с loopback-адреса этого сервера.")
        path = urlparse(self.path).path
        if path == "/api/health":
            # A web-server check must not wait for Codex, budgets or reconciliation.
            return self.send_json(HTTPStatus.OK, {"ok": True, "service": "portfolio-dashboard", "pid": os.getpid()})
        if path == "/api/board":
            return self.send_json(HTTPStatus.OK, {"board": self.board_state(), "projects": read_json(PROJECTS_FILE)})
        if path == "/api/models":
            try:
                return self.send_json(HTTPStatus.OK, {"models": BRIDGE.available_models()})
            except AppServerError as error:
                return self.send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "MODELS_UNAVAILABLE", str(error))
        if path == "/api/state":
            queue = copy.deepcopy(read_json(QUEUE_FILE))
            BRIDGE.schedule_reconciliation(queue)
            for item in queue:
                item["isStale"] = item_is_stale(item)
            budget = BRIDGE.current_budget()
            return self.send_json(
                HTTPStatus.OK,
                {
                    "projects": read_json(PROJECTS_FILE),
                    "board": self.board_state(),
                    "tomorrowPlan": read_json(TOMORROW_FILE),
                    "budget": budget,
                    "queue": queue,
                    "activity": read_json(ACTIVITY_FILE),
                    "dispatch": BRIDGE.snapshot(),
                    "serverTime": now(),
                    "staleAfterSeconds": 120,
                },
            )
        if path == "/api/bridge-health":
            if not is_codex_bridge():
                snapshot = BRIDGE.snapshot()
                return self.send_json(HTTPStatus.OK, {**snapshot, "checkedAt": now()})
            try:
                result = BRIDGE.request("thread/list", {"limit": 1}, timeout=30)
                return self.send_json(
                    HTTPStatus.OK,
                    {
                        "online": BRIDGE.online,
                        "runtime": BRIDGE.runtime,
                        "threadListReadable": isinstance(result, dict),
                        "checkedAt": now(),
                    },
                )
            except AppServerError as error:
                return self.send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"online": False, "error": str(error), "checkedAt": now()},
                )
        return self._serve_asset(path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._valid_write_request():
            return
        path = urlparse(self.path).path
        payload = self.read_body()
        if payload is None:
            return
        if path == "/api/shutdown":
            self.send_json(HTTPStatus.ACCEPTED, {"stopping": True})
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if path == "/api/board":
            return self.update_board(payload)
        if path == "/api/queue":
            return self.add_to_queue(payload)
        if path == "/api/queue/archive":
            return self.archive_queue(payload)
        if path == "/api/confirm-dispatch":
            return self.confirm_dispatch(payload)
        if path == "/api/retry-dispatch":
            return self.retry_dispatch(payload)
        self.send_api_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Неизвестный адрес API.")

    def board_state(self) -> dict[str, Any]:
        with DATA_LOCK:
            saved = read_json(BOARD_FILE) if BOARD_FILE.exists() else {}
            return normalize_board(saved, read_json(PROJECTS_FILE))

    def update_board(self, payload: dict[str, Any]) -> None:
        with DATA_LOCK:
            board = self.board_state()
            try:
                if payload.get("op") == "add-project":
                    if type(payload.get("revision")) is not int or payload["revision"] != board["revision"]:
                        raise BoardConflict("Доска изменилась. Повторите добавление.")
                    name = payload.get("name")
                    goal = payload.get("goal", "")
                    if not isinstance(name, str) or not name.strip() or len(name) > 160 or not isinstance(goal, str) or len(goal) > 2000:
                        raise ValueError("Укажите название до 160 символов и цель до 2000 символов.")
                    column_id = payload.get("columnId", "backlog")
                    if column_id not in {c["id"] for c in board["columns"]}:
                        raise ValueError("Колонка не найдена.")
                    workspace = workspace_for_planning(payload.get("workspace", ""))
                    projects = read_json(PROJECTS_FILE)
                    pid = "project-" + uuid.uuid4().hex[:12]
                    projects.append({"id": pid, "name": name.strip(), "goal": goal.strip() or "Уточнить цель проекта.", "stage": "Новая карточка. Выполнение ещё не запускалось.", "nextSteps": ["Уточнить ожидаемый результат.", "Добавить первое поручение.", "Проверить результат после выполнения."], "workspace": workspace, "route": {"status": "unconfigured", "label": "Укажите рабочую папку перед автоматическим запуском", "threadId": None}})
                    board = normalize_board(board, projects)
                    board = apply_operation(board, {"revision": board["revision"], "op": "move", "projectId": pid, "columnId": column_id})
                    board["history"] = [event for event in board.get("history", []) if event.get("projectId") != pid]
                    board["history"].append({"at":now(), "projectId":pid, "title":"Создана карточка", "text":name.strip()})
                    write_json(PROJECTS_FILE, projects)
                elif payload.get("op") == "set-workspace":
                    if type(payload.get("revision")) is not int or payload["revision"] != board["revision"]:
                        raise BoardConflict("Доска изменилась. Повторите изменение рабочей папки.")
                    project_id = payload.get("projectId")
                    if not isinstance(project_id, str):
                        raise ValueError("Не указан проект для рабочей папки.")
                    workspace = workspace_for_planning(payload.get("workspace", ""))
                    projects = read_json(PROJECTS_FILE)
                    project = next((item for item in projects if item.get("id") == project_id), None)
                    if project is None:
                        raise ValueError("Карточка проекта не найдена.")
                    if any(item.get("projectId") == project_id and item.get("status") in ACTIVE_STATUSES for item in read_json(QUEUE_FILE)):
                        raise BoardConflict("Нельзя менять рабочую папку, пока задача этого проекта выполняется.")
                    changed_workspace = project.get("workspace", "") != workspace
                    project["workspace"] = workspace
                    if changed_workspace:
                        route = {"status": "unconfigured", "label": "Рабочая папка изменена; выберите запуск заново", "threadId": None}
                        project["route"] = route
                        queue = read_json(QUEUE_FILE)
                        for item in queue:
                            if item.get("projectId") == project_id and item.get("status") not in TERMINAL_STATUSES:
                                item["route"] = copy.deepcopy(route)
                        write_json(QUEUE_FILE, queue)
                    board["revision"] += 1
                    board.setdefault("history", []).append({"at": now(), "projectId": project_id, "title": "Изменена рабочая папка", "text": workspace or "Не задана"})
                    write_json(PROJECTS_FILE, projects)
                else:
                    board = apply_operation(board, payload)
                board["updatedAt"] = now()
                write_json(BOARD_FILE, board)
            except BoardConflict as error:
                return self.send_json(HTTPStatus.CONFLICT, {"error": str(error), "board": self.board_state()})
            except (ValueError, TypeError, KeyError) as error:
                return self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_BOARD_CHANGE", str(error))
        self.send_json(HTTPStatus.OK, {"board": board, "projects": read_json(PROJECTS_FILE)})

    def read_body(self) -> dict[str, Any] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 100_000:
                raise ValueError("Размер запроса недопустим.")
            raw = self.rfile.read(content_length)
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("Ожидается JSON-объект.")
            return parsed
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", str(error))
            return None

    def add_to_queue(self, payload: dict[str, Any]) -> None:
        updates = payload.get("updates")
        projects = {project["id"]: project for project in read_json(PROJECTS_FILE)}
        if not isinstance(updates, list) or not updates:
            return self.send_api_error(HTTPStatus.BAD_REQUEST, "EMPTY_QUEUE", "Нужно добавить хотя бы одно изменение.")
        queue = read_json(QUEUE_FILE)
        accepted: list[dict[str, Any]] = []
        catalog = None
        for item in updates[:20]:
            if not isinstance(item, dict):
                continue
            project_id = item.get("projectId")
            kind = item.get("kind")
            text = str(item.get("text", "")).strip()
            scope = item.get("scope", "normal")
            if project_id not in projects or kind not in {"next-step", "goal", "comment"} or not text:
                continue
            if scope not in {"small", "normal", "deep"}:
                scope = "normal"
            model = item.get("model")
            if model is not None and not isinstance(model, str):
                return self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_MODEL", "Выберите модель из списка.")
            model = model.strip() or None if isinstance(model, str) else None
            if model:
                if catalog is None:
                    try:
                        catalog = {entry["id"]: entry for entry in BRIDGE.available_models()}
                    except AppServerError as error:
                        return self.send_api_error(HTTPStatus.SERVICE_UNAVAILABLE, "MODELS_UNAVAILABLE", str(error))
                if model not in catalog:
                    return self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_MODEL", "Выбранная модель недоступна. Обновите список и выберите модель заново; поручения не добавлены.")
            accepted.append(
                {
                    "id": f"q-{uuid.uuid4().hex[:14]}",
                    "projectId": project_id,
                    "projectName": projects[project_id]["name"],
                    "kind": kind,
                    "text": text[:2_000],
                    "scope": scope,
                    "model": model,
                    "modelLabel": catalog[model]["label"] if model else None,
                    "status": "queued",
                    "progress": 0,
                    "progressStage": "В очереди, ждёт подтверждения",
                    "createdAt": now(),
                    "route": projects[project_id]["route"],
                }
            )
        if not accepted:
            return self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_UPDATES", "Не удалось распознать изменения.")
        with DATA_LOCK:
            queue = read_json(QUEUE_FILE)
            queue.extend(accepted)
            write_json(QUEUE_FILE, queue)
        append_activity("queue", f"В очередь добавлено изменений: {len(accepted)}.")
        for item in accepted:
            record_event("task_queued", queue_id=item["id"])
        self.send_json(HTTPStatus.CREATED, {"added": accepted})

    def archive_queue(self, payload: dict[str, Any]) -> None:
        queue_ids, archived = payload.get("queueIds"), payload.get("archived")
        if (not isinstance(queue_ids, list) or not queue_ids or len(queue_ids) > 1000
                or not all(isinstance(value, str) and value for value in queue_ids)
                or not isinstance(archived, bool)):
            return self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_ARCHIVE_REQUEST", "Выберите поручения и действие с архивом.")
        with DATA_LOCK:
            queue = read_json(QUEUE_FILE)
            selected = [item for item in queue if item.get("id") in set(queue_ids)]
            if len(selected) != len(set(queue_ids)):
                return self.send_api_error(HTTPStatus.CONFLICT, "ARCHIVE_CONFLICT", "Список поручений изменился. Обновите журнал; ничего не перемещено.")
            if archived and any(item.get("status") not in {"completed", "failed", "interrupted"} for item in selected):
                return self.send_api_error(HTTPStatus.CONFLICT, "ARCHIVE_ACTIVE_TASK", "В архив можно убрать только завершённые, ошибочные и остановленные поручения. Ничего не перемещено.")
            changed = 0
            stamp = now()
            for item in selected:
                if bool(item.get("archivedAt")) == archived:
                    continue
                changed += 1
                if archived:
                    item["archivedAt"] = stamp
                else:
                    item.pop("archivedAt", None)
            if changed:
                write_json(QUEUE_FILE, queue)
                append_activity("archive", f"{'В архив перемещено' if archived else 'Из архива возвращено'} поручений: {changed}. Результаты сохранены; запуск не выполнялся.")
            updated = [{"id": item["id"], "archivedAt": item.get("archivedAt")} for item in selected]
        self.send_json(HTTPStatus.OK, {"updated": updated, "message": f"{'В архиве' if archived else 'Возвращено из архива'}: {len(selected)}. Поручения не запускались."})

    def confirm_dispatch(self, payload: dict[str, Any]) -> None:
        queue_ids = payload.get("queueIds")
        if not isinstance(queue_ids, list) or not all(isinstance(value, str) for value in queue_ids):
            return self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_QUEUE_IDS", "Неверный список задач.")
        queue = read_json(QUEUE_FILE)
        selected = [item for item in queue if item.get("id") in set(queue_ids) and item.get("status") == "queued" and not item.get("archivedAt")]
        if not selected:
            return self.send_api_error(HTTPStatus.CONFLICT, "NOTHING_TO_SEND", "Нет новых задач для отправки. Обновите экран.")
        try:
            for group in group_queue_items(selected):
                selected_model(group)
        except AppServerError as error:
            return self.send_api_error(HTTPStatus.CONFLICT, "MODEL_CONFLICT", str(error))
        try:
            for group in group_queue_items(selected):
                project = project_by_id(str(group[0].get("projectId")))
                if project is None:
                    raise AppServerError("Карточка проекта больше не существует.")
                validated_workspace(project.get("workspace"))
        except AppServerError as error:
            return self.send_api_error(HTTPStatus.UNPROCESSABLE_ENTITY, "WORKSPACE_REQUIRED", str(error))
        planned = dispatch_points(selected)
        budget = BRIDGE.current_budget()
        if not is_codex_bridge() and not budget.get("dispatchAllowed"):
            return self.send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "DISPATCH_UNAVAILABLE",
                "Выбранный bridge сейчас не разрешает автоматическую отправку. Очередь сохранена.",
            )
        if is_codex_bridge() and not budget.get("isLive"):
            return self.send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "LIMITS_UNAVAILABLE",
                "Не удалось проверить текущий лимит Codex. Повторите после восстановления связи — очередь сохранена.",
            )
        capacity = queue_capacity(budget) if is_codex_bridge() else None
        if capacity is not None and planned > capacity:
            return self.send_api_error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "BUDGET_EXCEEDED",
                f"Выбрано {planned} плановых единиц при доступных {capacity}%. Уменьшите пакет или дождитесь сброса лимита.",
            )
        selected_ids = {str(item["id"]) for item in selected}
        # Budget lookup can overlap an archive write or another confirmation.
        # Re-read and claim under the same lock; never overwrite that newer queue.
        with DATA_LOCK:
            queue = read_json(QUEUE_FILE)
            selected = [item for item in queue if item.get("id") in selected_ids and item.get("status") == "queued" and not item.get("archivedAt")]
            if len(selected) != len(selected_ids):
                return self.send_api_error(HTTPStatus.CONFLICT, "QUEUE_CHANGED", "Поручения уже изменились. Обновите журнал перед отправкой.")
            for item in selected:
                item.update({"status": "dispatching", "progress": 10, "progressStage": "Подключаем выбранного исполнителя", "lastEventAt": now()})
            write_json(QUEUE_FILE, queue)
        groups = group_queue_items(selected)
        for group in groups:
            group_ids = [str(item["id"]) for item in group]
            for queue_id in group_ids:
                record_event("task_claimed", queue_id=queue_id)
            threading.Thread(target=BRIDGE.dispatch_many, args=(group_ids,), name=f"portfolio-dispatch-{group_ids[0][-6:]}", daemon=True).start()
        append_activity("dispatch", f"Передано выбранному исполнителю ({bridge_kind()}): {len(selected_ids)} правок в {len(groups)} запуск(ах).")
        self.send_json(HTTPStatus.ACCEPTED, {"started": sorted(selected_ids), "message": f"Правки приняты: {len(selected_ids)} в {len(groups)} согласованных запуск(ах). Экран обновится автоматически по событиям исполнителя."})

    def retry_dispatch(self, payload: dict[str, Any]) -> None:
        queue_id = payload.get("queueId")
        if not isinstance(queue_id, str):
            return self.send_api_error(HTTPStatus.BAD_REQUEST, "INVALID_QUEUE_ID", "Не указан идентификатор задачи.")
        if not is_codex_bridge() and not BRIDGE.current_budget().get("dispatchAllowed"):
            return self.send_api_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "DISPATCH_UNAVAILABLE",
                "Выбранный bridge сейчас не разрешает автоматическую отправку. Задача не изменена.",
            )
        with DATA_LOCK:
            item = find_queue_item(queue_id)
            retryable_statuses = {"waiting-busy", "failed", "interrupted"}
            if item is None or item.get("archivedAt") or item.get("status") not in retryable_statuses:
                return self.send_api_error(HTTPStatus.CONFLICT, "RETRY_NOT_ALLOWED", "Эту задачу сейчас нельзя отправить повторно. Архивную запись сначала верните в журнал.")
            original_turn_id = item.get("turnId")
            group = [item]
            if isinstance(original_turn_id, str):
                group = [
                    candidate for candidate in read_json(QUEUE_FILE)
                    if candidate.get("projectId") == item.get("projectId")
                    and candidate.get("turnId") == original_turn_id
                    and candidate.get("status") in retryable_statuses
                    and not candidate.get("archivedAt")
                ]
            group_ids = [str(candidate["id"]) for candidate in group]
            for group_id in group_ids:
                update_queue_item(group_id, status="dispatching", progress=10, progressStage="Повторно подключаем выбранного исполнителя", error=None)
        threading.Thread(target=BRIDGE.dispatch_many, args=(group_ids,), name=f"portfolio-retry-{queue_id[-6:]}", daemon=True).start()
        self.send_json(HTTPStatus.ACCEPTED, {"started": group_ids, "message": f"Повторная отправка запущена: {len(group_ids)} связанной(ых) правок одним запуском."})

    def send_api_error(self, status: HTTPStatus, code: str, message: str) -> None:
        self.send_json(status, {"error": message, "code": code})

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not self._head_only:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), format % args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = ThreadingHTTPServer(("127.0.0.1", 5137), DashboardHandler)
    print("Project dashboard: http://127.0.0.1:5137")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
