"""Runtime-selection regression: no real Codex process or user queue writes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class RuntimeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='portfolio-runtime-test-')
        self.addCleanup(self.temp.cleanup)
        self.local = Path(self.temp.name)
        self.old = self.local / 'Programs/OpenAI/Codex/bin/codex.exe'
        self.new = self.local / 'OpenAI/Codex/bin/current-build/codex.exe'
        self.stale = self.local / 'OpenAI/Codex/bin/stale-build/codex.exe'
        self.versions = {str(self.old): '0.145.0', str(self.new): '0.153.4', str(self.stale): '0.99.0'}
        for path in [self.old, self.new, self.stale]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def run_version(self, args, **kwargs):
        return subprocess.CompletedProcess(args, 0, f'codex-cli {self.versions[str(args[0])]}\n', '')

    def start_bridge(self, override=''):
        bridge = server.CodexBridge()
        process = MagicMock()
        process.poll.return_value = None
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'LOCALAPPDATA': str(self.local), 'PORTFOLIO_CODEX_BIN': override}).start()
        patch('shutil.which', return_value=str(self.old)).start()
        patch('subprocess.run', side_effect=self.run_version).start()
        popen = patch('server.subprocess.Popen', return_value=process).start()
        patch('server.threading.Thread').start()
        patch('server.record_event').start()
        patch.object(bridge, 'request', return_value={}).start()
        patch.object(bridge, 'notify').start()
        bridge.start()
        return bridge, popen

    def test_old_path_entry_cannot_override_newer_desktop_runtime(self):
        _, popen = self.start_bridge()
        self.assertEqual(popen.call_args.args[0][0], str(self.new))

    def test_explicit_runtime_override_is_honored(self):
        _, popen = self.start_bridge(override=str(self.stale))
        self.assertEqual(popen.call_args.args[0][0], str(self.stale))

    def test_bad_override_fails_closed_instead_of_silently_using_path(self):
        with self.assertRaises(server.AppServerError):
            self.start_bridge(override=str(self.local / 'missing.exe'))


if __name__ == '__main__':
    unittest.main()
