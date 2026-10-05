"""Server-lifecycle checks. Never dispatches tasks or connects to Codex."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener
import test_board

server = test_board.server


class HealthTests(unittest.TestCase):
    setUp = test_board.HTTPTests.setUp
    tearDown = test_board.HTTPTests.tearDown

    def test_health_identifies_live_server_without_bridge_or_queue_access(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('Health must not call Codex or read the portfolio')
        server.BRIDGE.current_budget = forbidden
        server.BRIDGE.schedule_reconciliation = forbidden
        try:
            response = build_opener(ProxyHandler({})).open(self.base + '/api/health', timeout=3)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, 200)
            data = json.load(response)
        self.assertEqual(data['service'], 'portfolio-dashboard')
        self.assertEqual(data['pid'], os.getpid())
        self.assertTrue(data['ok'])


class ServiceLogTests(unittest.TestCase):
    def test_occupied_port_is_recorded_in_persistent_log_without_starting_work(self):
        with tempfile.TemporaryDirectory(prefix='portfolio-service-test-') as directory:
            with socket.socket() as occupied:
                occupied.bind(('127.0.0.1', 0))
                occupied.listen()
                port = occupied.getsockname()[1]
                result = subprocess.run([sys.executable, str(server.ROOT/'dashboard_service.py'),
                                         '--port', str(port), '--log-dir', directory], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            log = Path(directory, 'server.log').read_text(encoding='utf-8')
            self.assertIn('Service failed', log)
            self.assertIn(str(port), log)
            self.assertRegex(log, r'(OSError|PermissionError):')


if __name__ == '__main__':
    unittest.main()
