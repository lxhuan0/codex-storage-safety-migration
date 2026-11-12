import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'skills/codex-storage-migration/scripts/inventory.py'
spec = importlib.util.spec_from_file_location('inventory', SCRIPT)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def test_sizes_unicode_and_no_content_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'empty').mkdir()
            (root / '示例.txt').write_bytes(b'abc')
            (root / 'larger').write_bytes(b'12345')
            result = inventory.inspect_root(root, 1)
            self.assertTrue(result['complete'])
            self.assertEqual(result['logical_file_bytes'], 8)
            self.assertEqual(result['directories'], 2)
            self.assertEqual(result['largest_files'][0]['bytes'], 5)
            self.assertEqual((root / '示例.txt').read_bytes(), b'abc')

    def test_missing_is_error_not_zero_size_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = inventory.inspect_root(Path(directory) / 'missing')
            self.assertFalse(result['complete'])
            self.assertTrue(result['errors'])

    def test_link_target_and_link_ancestor_not_traversed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            target = root / 'target'
            source.mkdir()
            target.mkdir()
            (target / 'secret').write_bytes(b'do not count')
            (target / 'child').mkdir()
            link = source / 'link'
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest('Creating a symlink is not permitted in this environment')
            result = inventory.inspect_root(source)
            self.assertEqual(result['logical_file_bytes'], 0)
            self.assertEqual(len(result['skipped_redirects']), 1)
            self.assertFalse(inventory.inspect_root(link / 'child')['complete'])

    def test_hardlinks_are_flagged_not_called_reclaimed_space(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'original').write_bytes(b'abc')
            try:
                os.link(root / 'original', root / 'alias')
            except OSError:
                self.skipTest('Hardlinks not supported on this filesystem')
            result = inventory.inspect_root(root)
            self.assertEqual(result['hardlinked_files'], 2)
            self.assertEqual(result['logical_file_bytes'], 6)


if __name__ == '__main__':
    unittest.main()
