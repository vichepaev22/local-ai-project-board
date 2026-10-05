"""Hermes bridge lifecycle tests without provider calls or user config changes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_board import install_fixture, server

import hermes_bridge


def stream_result(text="Done", session_id="hermes-session", exit_code=0, error=None):
    events = [
        {"type": "system", "subtype": "init", "session_id": session_id},
        {"type": "text", "text": text},
        {"type": "result", "session_id": session_id, "exit_code": exit_code, "text": text},
    ]
    if error:
        events[-1]["error"] = error
    return "\n".join(json.dumps(event) for event in events) + "\n"


class FakeProcess:
    def __init__(self, stdout="", stderr="", returncode=0, timeout=False, gate=None):
        self.stdout_value = stdout
        self.stderr_value = stderr
        self.returncode = returncode
        self.timeout = timeout
        self.gate = gate
        self.killed = False
        self.inputs = []

    def communicate(self, input=None, timeout=None):
        self.inputs.append((input, timeout))
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("hermes", timeout)
        if self.gate is not None:
            self.gate.wait(3)
        return self.stdout_value, self.stderr_value

    def kill(self):
        self.killed = True

    def poll(self):
        return self.returncode


class HermesBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="project-board-hermes-", dir=Path(__file__).resolve().parent
        )
        self.addCleanup(self.temp.cleanup)
        original = {
            key: getattr(server, key)
            for key in [
                "PROJECTS_FILE", "QUEUE_FILE", "ACTIVITY_FILE", "BOARD_FILE",
                "TOMORROW_FILE", "BUDGET_FILE", "EVENTS_FILE", "BRIDGE",
            ]
        }
        self.addCleanup(lambda: [setattr(server, key, value) for key, value in original.items()])
        install_fixture(self.temp.name)
        self.env = {
            "PROJECT_BOARD_HERMES_BIN": str(Path(sys.executable).resolve()),
        }
        self.env_patch = patch.dict(os.environ, self.env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.project = server.project_by_id("one")

    def queue(self, *ids):
        route = dict(self.project["route"])
        items = [
            {
                "id": queue_id,
                "projectId": "one",
                "text": f"Request {queue_id}",
                "kind": "next-step",
                "status": "dispatching",
                "route": route,
                "lastEventAt": server.now(),
            }
            for queue_id in ids
        ]
        server.write_json(server.QUEUE_FILE, items)
        return items

    def run_with(self, process, ids=("q1",), bridge=None):
        self.queue(*ids)
        bridge = bridge or hermes_bridge.HermesBridge()
        calls = []

        def spawn(args, **kwargs):
            calls.append((args, kwargs))
            return process

        with patch.object(hermes_bridge.subprocess, "Popen", side_effect=spawn):
            bridge.dispatch_many(list(ids))
        return bridge, calls

    def test_snapshot_budget_and_models_do_not_probe_remote_catalog(self):
        bridge = hermes_bridge.HermesBridge()
        snapshot = bridge.snapshot()
        self.assertEqual(bridge.kind, "hermes")
        self.assertTrue(snapshot["online"])
        self.assertEqual(snapshot["kind"], "hermes")
        self.assertIn("Hermes", snapshot["message"])
        self.assertIn("не песочниц", snapshot["message"])
        budget = bridge.current_budget()
        self.assertFalse(budget["limitEnforced"])
        self.assertTrue(budget["dispatchAllowed"])
        self.assertFalse(budget["isLive"])
        self.assertIsNone(budget["fiveHour"]["remainingPercent"])
        self.assertIsNone(budget["weekly"]["remainingPercent"])
        self.assertEqual(bridge.available_models(), [])

    def test_literal_prompt_uses_stdin_and_safe_bounded_cli_flags(self):
        dangerous = 'literal "quote" $(touch NEVER) `whoami` & | ; < > \\ юникод'
        self.queue("q1")
        items = server.read_json(server.QUEUE_FILE)
        items[0]["text"] = dangerous
        server.write_json(server.QUEUE_FILE, items)
        process = FakeProcess(stream_result("Safe answer", "session-1"))
        bridge = hermes_bridge.HermesBridge()
        calls = []
        with patch.object(hermes_bridge.subprocess, "Popen", side_effect=lambda args, **kwargs: calls.append((args, kwargs)) or process):
            bridge.dispatch_many(["q1"])
        args, kwargs = calls[0]
        self.assertNotIn(dangerous, args)
        self.assertIn(dangerous, process.inputs[0][0])
        self.assertEqual(args[1:5], ["chat", "--query-file", "-", "--format"])
        self.assertIn("stream-json", args)
        self.assertNotIn("--oneshot", args)
        self.assertIn("--max-turns", args)
        self.assertEqual(args[args.index("--max-turns") + 1], "20")
        self.assertIn("--run-budget", args)
        self.assertIn("--no-restore-cwd", args)
        self.assertNotIn("--yolo", args)
        self.assertNotIn("--accept-hooks", args)
        self.assertNotIn("-z", args)
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["env"]["PYTHONUTF8"], "1")
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(Path(kwargs["cwd"]), Path(self.temp.name))
        item = server.find_queue_item("q1")
        self.assertEqual(item["status"], "completed")
        self.assertEqual(item["result"], "Safe answer")
        self.assertEqual(item["answerText"], "Safe answer")
        self.assertTrue(item["answerUpdatedAt"])
        self.assertEqual(item["route"], {
            "status": "linked", "label": "Hermes · Проверка один",
            "harness": "hermes", "sessionId": "session-1",
        })

    def test_model_provider_timeout_and_turn_bounds_are_validated_and_forwarded(self):
        os.environ.update({
            "PROJECT_BOARD_HERMES_MODEL": "configured/model",
            "PROJECT_BOARD_HERMES_PROVIDER": "configured-provider",
            "PROJECT_BOARD_HERMES_TIMEOUT": "42",
            "PROJECT_BOARD_HERMES_MAX_TURNS": "7",
        })
        process = FakeProcess(stream_result())
        bridge, calls = self.run_with(process)
        args = calls[0][0]
        self.assertEqual(bridge.available_models(), [{
            "id": "configured/model", "label": "configured/model", "isDefault": True,
        }])
        self.assertEqual(args[args.index("-m") + 1], "configured/model")
        self.assertEqual(args[args.index("--provider") + 1], "configured-provider")
        self.assertEqual(args[args.index("--max-turns") + 1], "7")
        self.assertEqual(args[args.index("--run-budget") + 1], "42")
        self.assertEqual(process.inputs[0][1], 42)
        for name, value in [
            ("PROJECT_BOARD_HERMES_TIMEOUT", "3601"),
            ("PROJECT_BOARD_HERMES_MAX_TURNS", "0"),
            ("PROJECT_BOARD_HERMES_MODEL", "bad\nmodel"),
            ("PROJECT_BOARD_HERMES_PROVIDER", "  "),
        ]:
            with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                invalid = hermes_bridge.HermesBridge()
                self.assertFalse(invalid.online)
                self.assertFalse(invalid.current_budget()["dispatchAllowed"])

    def test_resume_only_uses_hermes_session_never_codex_thread_id(self):
        projects = server.read_json(server.PROJECTS_FILE)
        projects[0]["route"] = {
            "harness": "hermes", "sessionId": "hermes-old", "threadId": "codex-never",
        }
        server.write_json(server.PROJECTS_FILE, projects)
        process = FakeProcess(stream_result("Continued", "hermes-new"))
        _, calls = self.run_with(process)
        args = calls[0][0]
        self.assertEqual(args[args.index("--resume") + 1], "hermes-old")
        self.assertNotIn("codex-never", args)
        self.assertEqual(server.find_queue_item("q1")["route"]["sessionId"], "hermes-new")
        self.assertNotIn("threadId", server.find_queue_item("q1")["route"])

    def test_codex_route_is_not_resumed_by_hermes(self):
        process = FakeProcess(stream_result("Fresh", "hermes-fresh"))
        _, calls = self.run_with(process)
        self.assertNotIn("--resume", calls[0][0])

    def test_provider_failure_is_safe_and_stderr_is_never_persisted(self):
        secret = "API_KEY=super-secret prompt=$(malicious)"
        process = FakeProcess(stream_result("", "s", exit_code=1, error=secret), stderr=secret, returncode=1)
        self.run_with(process)
        item = server.find_queue_item("q1")
        self.assertEqual(item["status"], "failed")
        self.assertNotIn("super-secret", item["error"])
        self.assertNotIn("malicious", item["error"])
        self.assertNotIn("answerText", item)

    def test_empty_or_unstructured_stdout_is_failure(self):
        for stdout in ["", "human banner only\n", json.dumps({"type": "result", "exit_code": 0, "text": ""})]:
            with self.subTest(stdout=stdout):
                process = FakeProcess(stdout)
                self.run_with(process)
                item = server.find_queue_item("q1")
                self.assertEqual(item["status"], "failed")
                self.assertNotIn("answerText", item)

    def test_timeout_kills_only_owned_process_and_fails_batch(self):
        process = FakeProcess(timeout=True)
        self.run_with(process, ids=("q1", "q2"))
        self.assertTrue(process.killed)
        self.assertEqual(len(process.inputs), 2)
        for item in server.read_json(server.QUEUE_FILE):
            self.assertEqual(item["status"], "failed")
            self.assertIn("лимит", item["error"])

    def test_timeout_cleanup_never_waits_unbounded_on_inherited_pipes(self):
        class Pipe:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class StubbornProcess:
            def __init__(self):
                self.killed = False
                self.stdin, self.stdout, self.stderr = Pipe(), Pipe(), Pipe()

            def kill(self):
                self.killed = True

            def communicate(self, input=None, timeout=None):
                self.assert_timeout = timeout
                raise subprocess.TimeoutExpired("hermes", timeout)

        process = StubbornProcess()
        hermes_bridge.HermesBridge._kill_owned_process(process)
        self.assertTrue(process.killed)
        self.assertEqual(process.assert_timeout, 5)
        self.assertTrue(all(pipe.closed for pipe in (process.stdin, process.stdout, process.stderr)))

    def test_same_project_is_serialized_and_second_batch_waits(self):
        first_started = threading.Event()
        release = threading.Event()
        processes = []

        class BlockingProcess(FakeProcess):
            def communicate(self, input=None, timeout=None):
                self.inputs.append((input, timeout))
                first_started.set()
                release.wait(3)
                return self.stdout_value, self.stderr_value

        def spawn(*args, **kwargs):
            process = BlockingProcess(stream_result("First complete", "first-session"))
            processes.append(process)
            return process

        self.queue("q1", "q2")
        bridge = hermes_bridge.HermesBridge()
        with patch.object(hermes_bridge.subprocess, "Popen", side_effect=spawn):
            worker = threading.Thread(target=bridge.dispatch_many, args=(["q1"],))
            worker.start()
            self.assertTrue(first_started.wait(2))
            bridge.dispatch_many(["q2"])
            self.assertEqual(server.find_queue_item("q2")["status"], "waiting-busy")
            release.set()
            worker.join(3)
        self.assertEqual(len(processes), 1)
        self.assertEqual(server.find_queue_item("q1")["status"], "completed")

    def test_restart_reconciliation_interrupts_persisted_active_jobs_without_execution(self):
        self.queue("q1", "q2")
        queue = server.read_json(server.QUEUE_FILE)
        for item in queue:
            item["lastEventAt"] = "2000-01-01T00:00:00+00:00"
        queue[0].update(status="running", route={"harness": "hermes", "sessionId": "old"})
        # The selected process-wide bridge is Hermes. A crash can leave a just-
        # claimed item carrying its prior Codex route, so the stale route alone
        # must not hide it from restart recovery.
        queue[1].update(status="dispatching", route={"harness": "codex", "threadId": "codex"})
        server.write_json(server.QUEUE_FILE, queue)
        bridge = hermes_bridge.HermesBridge()
        with patch.object(hermes_bridge.subprocess, "Popen") as popen:
            bridge.schedule_reconciliation(server.read_json(server.QUEUE_FILE))
            bridge.schedule_reconciliation(server.read_json(server.QUEUE_FILE))
        popen.assert_not_called()
        self.assertEqual(server.find_queue_item("q1")["status"], "interrupted")
        self.assertEqual(server.find_queue_item("q2")["status"], "interrupted")

    def test_reconciliation_does_not_interrupt_newly_claimed_job(self):
        bridge = hermes_bridge.HermesBridge()
        self.queue("fresh")
        bridge.schedule_reconciliation(server.read_json(server.QUEUE_FILE))
        self.assertEqual(server.find_queue_item("fresh")["status"], "dispatching")

    def test_close_stops_owned_run_and_never_overwrites_interruption_with_success(self):
        started, release = threading.Event(), threading.Event()
        class ClosingProcess(FakeProcess):
            def communicate(self, input=None, timeout=None):
                started.set()
                release.wait(3)
                return stream_result('Should not be accepted'), ''
            def kill(self):
                self.killed=True
                release.set()
            def wait(self, timeout=None):
                return 0
        process=ClosingProcess()
        bridge=hermes_bridge.HermesBridge()
        self.queue('close-run')
        with patch.object(hermes_bridge.subprocess,'Popen',return_value=process):
            worker=threading.Thread(target=bridge.dispatch_many,args=(['close-run'],))
            worker.start()
            self.assertTrue(started.wait(2))
            bridge.close()
            bridge.close()
            worker.join(3)
        self.assertTrue(process.killed)
        self.assertFalse(worker.is_alive())
        self.assertEqual(server.find_queue_item('close-run')['status'],'interrupted')
        self.assertNotIn('answerText',server.find_queue_item('close-run'))
        self.assertFalse(bridge.online)

    def test_real_subprocess_literal_input_and_bounded_output(self):
        self.queue('literal')
        bridge=hermes_bridge.HermesBridge()
        code="import sys,json; text=sys.stdin.read(); print(json.dumps({'type':'result','session_id':'synthetic','exit_code':0,'text':text}))"
        with patch.object(bridge,'_command',return_value=[sys.executable,'-c',code]):
            bridge.dispatch_many(['literal'])
        self.assertEqual(server.find_queue_item('literal')['status'],'completed', server.find_queue_item('literal').get('error'))
        self.assertIn('Request literal',server.find_queue_item('literal')['answerText'])
        self.queue('overflow')
        code="import sys; sys.stdin.read(); sys.stdout.write('x'*2100000); sys.stdout.flush()"
        with patch.object(bridge,'_command',return_value=[sys.executable,'-c',code]):
            bridge.dispatch_many(['overflow'])
        self.assertEqual(server.find_queue_item('overflow')['status'],'failed')
        self.assertIn('размер',server.find_queue_item('overflow')['error'])


if __name__ == "__main__":
    unittest.main()
