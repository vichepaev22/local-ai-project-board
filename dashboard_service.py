"""HTTP service entry point used by :mod:`run` and legacy direct invocations."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import threading
from pathlib import Path
import webbrowser


def _configure_logging(log_dir: Path) -> tuple[logging.Logger, RotatingFileHandler]:
    selected = log_dir.expanduser().resolve()
    selected.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        selected / "server.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
        force=True,
    )
    return logging.getLogger("portfolio_service"), handler


def serve(port: int, log_dir: Path, *, open_browser: bool = False) -> int:
    """Serve loopback HTTP without dispatching or recovering saved work."""
    log, handler = _configure_logging(log_dir)
    log.info("Starting pid=%s parent=%s port=%s", os.getpid(), os.getppid(), port)
    http = None
    bridge = None
    previous_signal=None
    if threading.current_thread() is threading.main_thread():
        previous_signal=signal.getsignal(signal.SIGTERM)
        def stop_signal(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,stop_signal)
    try:
        # Keep this import after run.py has selected runtime environment values.
        from server import DashboardHandler, ThreadingHTTPServer, BRIDGE

        bridge = BRIDGE
        http = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
        url = f"http://127.0.0.1:{port}/"
        log.info("Ready %s; saved tasks are not dispatched on startup", url)
        if open_browser:
            webbrowser.open(url)
        http.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopped by keyboard interrupt")
    except Exception:
        log.exception("Service failed on port %s", port)
        return 1
    finally:
        if previous_signal is not None:
            signal.signal(signal.SIGTERM,previous_signal)
        if http is not None:
            http.server_close()
        # Bridges supplied by older servers do not need to implement shutdown.
        # When an adapter does expose close(), it owns only its own child process.
        close = getattr(bridge, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.exception("Bridge cleanup failed")
        log.info("Service exited pid=%s", os.getpid())
        handler.flush()
        handler.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    # Reuse the public CLI grammar so direct dashboard_service.py calls retain
    # compatibility while run.py remains the documented entry point.
    from run import main as run_main, parse_args, prepare_environment

    args = parse_args(argv)
    if args.background:
        return run_main(argv)
    prepare_environment(args)
    return serve(args.port, args.log_dir, open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main())
