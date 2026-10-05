"""Portable local launcher for the project board.

No server module is imported until the requested bridge and data directory have
been selected, so a fresh clone never imports private default paths.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser


ROOT = Path(__file__).resolve().parent
BRIDGES = ("manual", "codex", "hermes")


def port_number(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer from 1 through 65535") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be from 1 through 65535")
    return port


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local AI project board.")
    parser.add_argument("--bridge", choices=BRIDGES, default="manual", help="execution bridge; manual is the safe default")
    parser.add_argument("--port", type=port_number, default=5137, help="loopback TCP port (default: 5137)")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="directory for local JSON data")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "logs", help="directory for service logs")
    parser.add_argument("--open", action="store_true", help="open the board after the service is healthy")
    parser.add_argument("--background", action="store_true", help="start one child service and return after health verification")
    parser.add_argument("--stop", action="store_true", help="gracefully stop this board on the selected loopback port")
    return parser.parse_args(argv)


def prepare_environment(args: argparse.Namespace) -> None:
    os.environ["PROJECT_BOARD_BRIDGE"] = args.bridge
    os.environ["PROJECT_BOARD_DATA_DIR"] = str(args.data_dir.expanduser().resolve())


def wait_for_health(
    port: int, expected_pid: int, timeout: float = 8.0, process: subprocess.Popen[object] | None = None
) -> bool:
    """Check the expected child, without inheriting a web proxy."""
    opener = build_opener(ProxyHandler({}))
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            with opener.open(Request(url), timeout=min(1.0, max(0.1, deadline - time.monotonic()))) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status != 200 or not isinstance(payload, dict):
                    continue
                if payload.get("service") == "portfolio-dashboard" and payload.get("pid") == expected_pid:
                    return True
                # A responding process already owns the requested endpoint.
                # Do not wait for it, and never try to terminate that process.
                return False
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            time.sleep(0.1)
    return False


def background_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "run.py"),
        "--bridge",
        args.bridge,
        "--port",
        str(args.port),
        "--data-dir",
        str(args.data_dir.expanduser().resolve()),
        "--log-dir",
        str(args.log_dir.expanduser().resolve()),
    ]


def start_background(args: argparse.Namespace) -> int:
    child_environment = os.environ.copy()
    prepare_environment(args)
    child_environment.update({
        "PROJECT_BOARD_BRIDGE": os.environ["PROJECT_BOARD_BRIDGE"],
        "PROJECT_BOARD_DATA_DIR": os.environ["PROJECT_BOARD_DATA_DIR"],
    })
    options: dict[str, object] = {
        "cwd": str(ROOT),
        "env": child_environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = startupinfo
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    child = subprocess.Popen(background_command(args), **options)  # type: ignore[arg-type]
    if not wait_for_health(args.port, child.pid, process=child):
        # This is the process created above, not an attempt to manage any listener
        # that happened to occupy the requested port.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
        print(f"Board did not become healthy at http://127.0.0.1:{args.port}/api/health", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Board is running at {url} (pid {child.pid}).")
    if args.open:
        webbrowser.open(url)
    return 0


def start_foreground(args: argparse.Namespace) -> int:
    prepare_environment(args)
    # Imported late: server obtains runtime paths and bridge selection from env.
    from dashboard_service import serve

    return serve(args.port, args.log_dir, open_browser=args.open)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.stop:
        opener=build_opener(ProxyHandler({}))
        try:
            with opener.open(f'http://127.0.0.1:{args.port}/api/health',timeout=3) as response:
                health=json.load(response)
            if health.get('service') != 'portfolio-dashboard':
                raise ValueError('The listener is not this project board.')
            request=Request(f'http://127.0.0.1:{args.port}/api/shutdown',data=b'{}',headers={'Content-Type':'application/json'})
            with opener.open(request,timeout=3) as response:
                if response.status != 202: raise ValueError('Shutdown not accepted.')
            print(f'Shutdown requested on port {args.port}.')
            return 0
        except (OSError,ValueError) as error:
            print(f'Could not stop this board: {error}',file=sys.stderr)
            return 1
    return start_background(args) if args.background else start_foreground(args)


if __name__ == "__main__":
    raise SystemExit(main())
