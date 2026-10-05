"""Fresh-clone launcher checks using only temporary data and a manual bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runtime_data  # noqa: E402


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def get_json(url: str, timeout: float = 1.0) -> tuple[int, dict]:
    """Explicitly bypass ambient HTTP proxy settings for loopback checks."""
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url), timeout=timeout) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))


def get_status(url: str, timeout: float = 1.0) -> int:
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url), timeout=timeout) as response:
        return int(response.status)


class RuntimeDataTests(unittest.TestCase):
    def test_fresh_initialization_creates_generic_empty_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-board-data-") as raw:
            files = runtime_data.initialize_data(Path(raw))
            self.assertEqual(set(files), {"DATA", *runtime_data.FILE_NAMES})
            self.assertEqual(json.loads(files["PROJECTS_FILE"].read_text(encoding="utf-8")), [])
            self.assertEqual(json.loads(files["QUEUE_FILE"].read_text(encoding="utf-8")), [])
            self.assertEqual(json.loads(files["ACTIVITY_FILE"].read_text(encoding="utf-8")), [])
            self.assertEqual(json.loads(files["BOARD_FILE"].read_text(encoding="utf-8")), {})
            self.assertEqual(json.loads(files["TOMORROW_FILE"].read_text(encoding="utf-8"))["tasks"], [])
            budget = json.loads(files["BUDGET_FILE"].read_text(encoding="utf-8"))
            self.assertFalse(budget["isLive"])
            self.assertIsNone(budget["fiveHour"]["remainingPercent"])
            self.assertIsNone(budget["weekly"]["remainingPercent"])
            self.assertTrue(budget["note"])
            self.assertEqual(files["EVENTS_FILE"].read_text(encoding="utf-8"), "")

    def test_repeat_initialization_never_overwrites_existing_or_corrupt_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-board-data-") as raw:
            data_dir = Path(raw)
            files = runtime_data.initialize_data(data_dir)
            files["PROJECTS_FILE"].write_text('[{"id":"kept"}]\n', encoding="utf-8")
            files["BOARD_FILE"].write_text('{not valid json', encoding="utf-8")
            again = runtime_data.initialize_data(data_dir)
            self.assertEqual(again["PROJECTS_FILE"].read_text(encoding="utf-8"), '[{"id":"kept"}]\n')
            self.assertEqual(again["BOARD_FILE"].read_text(encoding="utf-8"), '{not valid json')


class CliTests(unittest.TestCase):
    def test_invalid_arguments_are_rejected(self) -> None:
        for arguments in (("--port", "0"), ("--port", "65536"), ("--bridge", "other")):
            result = subprocess.run(
                [sys.executable, str(ROOT / "run.py"), *arguments],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=8,
            )
            self.assertNotEqual(result.returncode, 0, arguments)

    def test_launchers_do_not_embed_a_machine_python_path(self) -> None:
        for relative in ("run.py", "dashboard_service.py", "Start-Dashboard.cmd", "Start-Dashboard.ps1", "start.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("C:\\\\", text, relative)
        powershell = (ROOT / "Start-Dashboard.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-Command", powershell)


class ForegroundLaunchTests(unittest.TestCase):
    def test_manual_default_serves_fresh_custom_data_on_loopback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-board-run-") as raw:
            data_dir = Path(raw) / "board-data"
            log_dir = Path(raw) / "board-logs"
            port = unused_port()
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "run.py"),
                    "--port",
                    str(port),
                    "--data-dir",
                    str(data_dir),
                    "--log-dir",
                    str(log_dir),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 8
                last_error: OSError | None = None
                while time.monotonic() < deadline:
                    try:
                        status, health = get_json(f"http://127.0.0.1:{port}/api/health")
                        break
                    except OSError as error:
                        last_error = error
                        time.sleep(0.1)
                else:
                    stdout, stderr = process.communicate(timeout=1)
                    self.fail(f"manual service did not become healthy: {last_error}; stdout={stdout!r}; stderr={stderr!r}")
                self.assertEqual(status, 200)
                self.assertTrue(health["ok"])
                _, state = get_json(f"http://127.0.0.1:{port}/api/state")
                self.assertEqual(state["projects"], [])
                self.assertEqual(state["queue"], [])
                self.assertFalse(state["budget"]["isLive"])
                self.assertEqual(get_status(f"http://127.0.0.1:{port}/"), 200)
                self.assertEqual(json.loads((data_dir / "projects.json").read_text(encoding="utf-8")), [])
                stopped=subprocess.run([sys.executable,str(ROOT/'run.py'),'--stop','--port',str(port)],capture_output=True,timeout=5)
                self.assertEqual(stopped.returncode,0)
                process.wait(timeout=5)
                self.assertEqual(process.returncode,0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                else:
                    process.wait(timeout=1)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    def test_background_rejects_a_port_owned_by_another_process(self) -> None:
        class ForeignHealthHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = json.dumps(
                    {"ok": True, "service": "portfolio-dashboard", "pid": os.getpid()}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        foreign = ThreadingHTTPServer(("127.0.0.1", 0), ForeignHealthHandler)
        worker = threading.Thread(target=foreign.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory(prefix="project-board-background-") as raw:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "run.py"),
                        "--background",
                        "--port",
                        str(foreign.server_port),
                        "--data-dir",
                        str(Path(raw) / "data"),
                        "--log-dir",
                        str(Path(raw) / "logs"),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                    timeout=10,
                )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(get_json(f"http://127.0.0.1:{foreign.server_port}/api/health")[0], 200)
        finally:
            foreign.shutdown()
            foreign.server_close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
