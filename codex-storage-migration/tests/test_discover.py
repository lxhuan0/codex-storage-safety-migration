import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'skills/codex-storage-migration/scripts/discover.py'
spec = importlib.util.spec_from_file_location('discover', SCRIPT)
discover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discover)


class DiscoveryTests(unittest.TestCase):
    def test_explicit_home_and_environment_are_used(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {'CODEX_HOME': str(root / 'custom'), 'CODEX_SQLITE_HOME': str(root / 'state'),
                   'LOCALAPPDATA': str(root / 'local'), 'APPDATA': str(root / 'roaming'), 'PATH': ''}
            report = discover.discover(root, env, 'win32')
            paths = {entry['category']: entry['path'] for entry in report['candidates']}
            self.assertEqual(paths['codex-home'], str(root / 'custom'))
            self.assertEqual(paths['desktop-profile'], str(root / 'roaming/Codex'))
            self.assertFalse((root / 'custom').exists())

    def test_other_platforms_are_candidates_not_windows_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            report = discover.discover(directory, {'PATH': ''}, 'darwin')
            self.assertTrue(any('Library' in entry['path'] for entry in report['candidates']))
            self.assertIsNone(report['cli_on_path'])
