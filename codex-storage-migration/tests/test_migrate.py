"""All mutations are confined to a new TemporaryDirectory, never real Codex data.

The process guard is mocked because these fixtures have no relationship to the
running application. Production command-line invocations cannot bypass it.
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / 'skills/codex-storage-migration/scripts'
sys.path.insert(0, str(SCRIPTS))
import migrate as m
import windows_fs as fs
COLD_IMPL = m.assert_cold


@unittest.skipUnless(os.name == 'nt', 'Windows NTFS executor')
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-skill-fixture-')
        self.root = Path(self.temp.name)
        self.addCleanup(self.cleanup_fixture)
        self.source = self.root / 'source'
        self.target = self.root / 'destination'
        self.originals = self.root / 'retained-originals'
        for directory in (self.source, self.target, self.originals):
            directory.mkdir()
        (self.source / 'empty').mkdir()
        (self.source / '目录').mkdir()
        (self.source / '目录/示例.bin').write_bytes(b'original\0payload')
        (self.source / 'version.txt').write_text('generation-one', encoding='utf-8')
        self.output = io.StringIO()
        redirection = redirect_stdout(self.output)
        redirection.__enter__()
        self.addCleanup(redirection.__exit__, None, None, None)
        guard = patch.object(m, 'assert_cold')
        guard.start()
        self.addCleanup(guard.stop)
        self.addCleanup(setattr, m, 'FAILPOINT', None)

    def cleanup_fixture(self):
        # Only this test's freshly created fixture, with long-path support.
        assert self.root.parent == Path(tempfile.gettempdir())
        assert self.root.name.startswith('codex-skill-fixture-')
        if os.path.lexists(fs.native(self.root)):
            def retry_readonly(function, path, error):
                if not isinstance(error, PermissionError):
                    raise error
                info = os.lstat(path)
                fs.check(fs.K.SetFileAttributesW(path, info.st_file_attributes & ~1))
                function(path)
            shutil.rmtree(fs.native(self.root), onexc=retry_readonly)
        self.temp.cleanup()

    def prepare(self):
        return m.prepare(self.source, self.target, self.originals)

    def fail_once(self, phase):
        hit = []
        def hook(name):
            if name == phase and not hit:
                hit.append(True)
                raise RuntimeError('synthetic interruption: ' + phase)
        m.FAILPOINT = hook

    def journal(self, job):
        return m.read_json(job / 'journal.json')

    def test_roundtrip_retains_latest_changes(self):
        job = self.prepare()
        m.apply(job)
        self.assertEqual(self.journal(job)['stage'], 'Linked')
        original = Path(self.journal(job)['original'])
        self.assertTrue(original.exists())
        (self.source / 'new-data.txt').write_bytes(b'latest data after cutover')
        m.return_latest(job)
        self.assertEqual((self.source / 'new-data.txt').read_bytes(), b'latest data after cutover')
        self.assertNotEqual(getattr(os.lstat(self.source), 'st_reparse_tag', 0), 0xA0000003)
        self.assertTrue((job / 'baseline').is_dir())

    def test_interrupted_after_park_can_recover_original(self):
        job = self.prepare()
        self.fail_once('parked')
        with self.assertRaisesRegex(RuntimeError, 'synthetic interruption'):
            m.apply(job)
        self.assertFalse(self.source.exists())
        m.recover_original(job)
        self.assertEqual((self.source / 'version.txt').read_text(), 'generation-one')

    def test_crash_between_rename_and_journal_resumes(self):
        job = self.prepare()
        self.fail_once('after-park-before-journal')
        with self.assertRaises(RuntimeError):
            m.apply(job)
        self.assertEqual(self.journal(job)['stage'], 'CopiesVerified')
        m.FAILPOINT = None
        m.apply(job)
        m.exact_portal(self.source, job / 'active')

    def test_crash_between_link_and_journal_resumes(self):
        job = self.prepare()
        self.fail_once('after-link-before-journal')
        with self.assertRaises(RuntimeError):
            m.apply(job)
        m.FAILPOINT = None
        m.apply(job)
        self.assertEqual(self.journal(job)['stage'], 'Linked')

    def test_partial_complete_file_copy_resumes(self):
        job = self.prepare()
        self.fail_once('copy-entry')
        with self.assertRaises(RuntimeError):
            m.apply(job)
        m.FAILPOINT = None
        m.apply(job)
        self.assertEqual(self.journal(job)['stage'], 'Linked')

    def test_corrupt_backup_blocks_source_retirement(self):
        job = self.prepare()
        m.apply(job)
        m.mark_verified(job)
        (job / 'baseline/version.txt').write_bytes(b'corrupted')
        with self.assertRaisesRegex(RuntimeError, 'Verification differs'):
            m.retire_original(job)
        self.assertTrue(Path(self.journal(job)['original']).exists())

    def test_retirement_requires_actual_use_acknowledgement(self):
        job = self.prepare()
        m.apply(job)
        with self.assertRaisesRegex(RuntimeError, 'Application verification'):
            m.retire_original(job)

    def test_interrupted_retirement_then_latest_return(self):
        job = self.prepare()
        m.apply(job)
        m.mark_verified(job)
        self.fail_once('retire-entry')
        with self.assertRaises(RuntimeError):
            m.retire_original(job)
        m.FAILPOINT = None
        m.retire_original(job)
        self.assertFalse(Path(self.journal(job)['original']).exists())
        (self.source / 'version.txt').write_bytes(b'changed after retirement')
        m.return_latest(job)
        self.assertEqual((self.source / 'version.txt').read_bytes(), b'changed after retirement')

    def test_return_interrupted_after_portal_removed_resumes(self):
        job = self.prepare()
        m.apply(job)
        (self.source / 'latest').write_bytes(b'new')
        self.fail_once('after-unlink-before-return')
        with self.assertRaises(RuntimeError):
            m.return_latest(job)
        self.assertFalse(self.source.exists())
        m.FAILPOINT = None
        m.return_latest(job)
        self.assertEqual((self.source / 'latest').read_bytes(), b'new')

    def test_return_interrupted_after_rename_resumes(self):
        job = self.prepare()
        m.apply(job)
        self.fail_once('after-return-before-journal')
        with self.assertRaises(RuntimeError):
            m.return_latest(job)
        m.FAILPOINT = None
        m.return_latest(job)
        self.assertEqual(self.journal(job)['stage'], 'ReturnedLatest')

    def test_recreated_source_is_preserved(self):
        job = self.prepare()
        self.fail_once('parked')
        with self.assertRaises(RuntimeError):
            m.apply(job)
        self.source.mkdir()
        (self.source / 'new-version').write_bytes(b'do not overwrite')
        m.FAILPOINT = None
        with self.assertRaises(RuntimeError):
            m.apply(job)
        with self.assertRaises(RuntimeError):
            m.recover_original(job)
        self.assertEqual((self.source / 'new-version').read_bytes(), b'do not overwrite')

    def test_hardlink_refused_before_source_mutation(self):
        os.link(self.source / 'version.txt', self.source / 'alias')
        job = self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'hardlinked'):
            m.apply(job)
        self.assertTrue((self.source / 'alias').exists())

    def test_nested_junction_refused_before_source_mutation(self):
        outside = self.root / 'outside'
        outside.mkdir()
        fs.junction(self.source / 'nested-link', outside)
        job = self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'attributes'):
            m.apply(job)
        self.assertTrue(self.source.exists())

    def test_named_stream_and_security_survive_roundtrip(self):
        path = self.source / 'version.txt'
        with open(str(path) + ':fixture:$DATA', 'wb') as stream:
            stream.write(b'alternate-stream')
        original = fs.metadata(path)
        job = self.prepare()
        m.apply(job)
        m.return_latest(job)
        with open(str(path) + ':fixture:$DATA', 'rb') as stream:
            self.assertEqual(stream.read(), b'alternate-stream')
        returned = fs.metadata(path)
        self.assertEqual(original['access'], returned['access'])
        self.assertEqual(original['created'], returned['created'])
        self.assertEqual(original['written'], returned['written'])

    def test_closed_sqlite_data_remains_queryable(self):
        path = self.source / 'state.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('create table records (value text)')
            db.execute('insert into records values (?)', ('retained',))
        db.close()
        job = self.prepare()
        m.apply(job)
        with sqlite3.connect(self.source / 'state.sqlite') as db:
            self.assertEqual(db.execute('select value from records').fetchone(), ('retained',))
        db.close()

    def test_changed_original_not_deleted(self):
        job = self.prepare()
        m.apply(job)
        m.mark_verified(job)
        path = Path(self.journal(job)['original']) / 'version.txt'
        path.write_bytes(b'unexpected new original data')
        with self.assertRaises(RuntimeError):
            m.retire_original(job)
        self.assertEqual(path.read_bytes(), b'unexpected new original data')

    def test_directory_stream_changed_during_retirement_is_preserved(self):
        with open(str(self.source) + ':root-stream:$DATA', 'wb') as stream:
            stream.write(b'old directory stream')
        job = self.prepare()
        m.apply(job)
        m.mark_verified(job)
        self.fail_once('retire-entry')
        with self.assertRaises(RuntimeError):
            m.retire_original(job)
        original = Path(self.journal(job)['original'])
        with open(str(original) + ':root-stream:$DATA', 'wb') as stream:
            stream.write(b'new unexpected stream data')
        m.FAILPOINT = None
        with self.assertRaisesRegex(RuntimeError, 'streams changed'):
            m.retire_original(job)
        with open(str(original) + ':root-stream:$DATA', 'rb') as stream:
            self.assertEqual(stream.read(), b'new unexpected stream data')

    def test_job_path_tampering_is_refused(self):
        job = self.prepare()
        state = self.journal(job)
        state['original'] = str(self.root / 'unrelated')
        m.atomic_json(job / 'journal.json', state)
        with self.assertRaisesRegex(RuntimeError, 'unbound'):
            m.apply(job)

    def test_exclusive_job_lock_prevents_second_operation(self):
        job = self.prepare()
        with m.job_lock(job):
            with self.assertRaisesRegex(RuntimeError, 'Another operation'):
                with m.job_lock(job):
                    pass

    def test_runtime_process_guard_refuses_without_killing(self):
        job = self.prepare()
        state = self.journal(job)
        with patch.object(fs, 'process_images', return_value=[
                dict(pid=123, name='worker.exe', image=str(self.source / 'worker.exe'))]):
            with self.assertRaisesRegex(RuntimeError, 'still running'):
                COLD_IMPL(state)

    def test_runtime_marker_change_refused_but_new_cache_allowed(self):
        job = m.prepare(self.source, self.target, self.originals, kind='runtime', pins=['version.txt'])
        (self.source / '__pycache__').mkdir()
        (self.source / '__pycache__/fixture.pyc').write_bytes(b'new cache')
        m.apply(job)
        self.assertEqual(self.journal(job)['stage'], 'Linked')
        m.return_latest(job)
        second = m.prepare(self.source, self.target, self.originals, kind='runtime', pins=['version.txt'])
        (self.source / 'version.txt').write_bytes(b'generation-two')
        with self.assertRaisesRegex(RuntimeError, 'generation marker changed'):
            m.apply(second)
        self.assertEqual((self.source / 'version.txt').read_bytes(), b'generation-two')

    def test_new_writer_during_copy_blocks_switch(self):
        job = self.prepare()
        once = []
        def hook(phase):
            if phase == 'copy-entry' and not once:
                once.append(True)
                (self.source / 'unexpected-writer').write_bytes(b'new data')
        m.FAILPOINT = hook
        with self.assertRaisesRegex(RuntimeError, 'Verification differs'):
            m.apply(job)
        self.assertTrue(self.source.is_dir())
        self.assertEqual((self.source / 'unexpected-writer').read_bytes(), b'new data')

    def test_live_file_handle_blocks_copy_without_source_change(self):
        job = self.prepare()
        handle = fs.open_handle(self.source / 'version.txt', 0x80000000, 0)
        try:
            with self.assertRaises(OSError):
                m.apply(job)
        finally:
            fs.K.CloseHandle(handle)
        self.assertFalse(self.source.is_symlink())
        self.assertEqual((self.source / 'version.txt').read_text(), 'generation-one')

    def test_truncated_partial_payload_is_preserved_and_refused(self):
        job = self.prepare()
        self.fail_once('baseline-verified')
        with self.assertRaises(RuntimeError):
            m.apply(job)
        path = job / 'baseline/version.txt'
        path.write_bytes(b'truncated')
        m.FAILPOINT = None
        with self.assertRaisesRegex(RuntimeError, 'Incomplete/changed'):
            m.apply(job)
        self.assertEqual(path.read_bytes(), b'truncated')
        self.assertTrue(self.source.exists())

    def test_missing_recovery_code_refused(self):
        job = self.prepare()
        (job / 'tools/windows_fs.py').unlink()
        with self.assertRaises(OSError):
            m.apply(job)
        self.assertTrue(self.source.exists())

    def test_return_refuses_data_written_after_latest_snapshot(self):
        job = self.prepare()
        m.apply(job)
        self.fail_once('return-ready')
        with self.assertRaises(RuntimeError):
            m.return_latest(job)
        (self.source / 'version.txt').write_bytes(b'newer than return staging')
        m.FAILPOINT = None
        with self.assertRaisesRegex(RuntimeError, 'Verification differs'):
            m.return_latest(job)
        self.assertEqual((self.source / 'version.txt').read_bytes(), b'newer than return staging')
        previous = Path(self.journal(job)['return_tree'])
        m.restart_return(job)
        self.assertTrue(previous.is_dir())
        m.return_latest(job)
        self.assertEqual((self.source / 'version.txt').read_bytes(), b'newer than return staging')

    def test_manifest_journal_gap_resumes_without_rebasing(self):
        job = self.prepare()
        self.fail_once('manifest-written-before-stage')
        with self.assertRaises(RuntimeError):
            m.apply(job)
        self.assertEqual(self.journal(job)['stage'], 'Planned')
        m.FAILPOINT = None
        m.apply(job)
        self.assertEqual(self.journal(job)['stage'], 'Linked')

    def test_manifest_journal_gap_refuses_changed_source(self):
        job = self.prepare()
        self.fail_once('manifest-written-before-stage')
        with self.assertRaises(RuntimeError):
            m.apply(job)
        (self.source / 'version.txt').write_bytes(b'changed between attempts')
        m.FAILPOINT = None
        with self.assertRaisesRegex(RuntimeError, 'Captured source changed'):
            m.apply(job)
        self.assertEqual((self.source / 'version.txt').read_bytes(), b'changed between attempts')

    def test_insufficient_space_refused_before_copy_or_rename(self):
        job = self.prepare()
        with patch.object(m.shutil, 'disk_usage', return_value=type('Space', (), {'free': 0})()):
            with self.assertRaisesRegex(RuntimeError, 'Insufficient space'):
                m.apply(job)
        self.assertTrue(self.source.exists())

    def test_cli_mutation_requires_explicit_flags(self):
        job = self.prepare()
        result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'migrate.py'),
                                 'apply', '--job', str(job)], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.journal(job)['stage'], 'Planned')

    def test_cli_status_from_independent_copied_toolkit(self):
        job = self.prepare()
        result = subprocess.run([sys.executable, '-B', str(job / 'tools/migrate.py'),
                                 'status', '--job', str(job)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'Planned', result.stdout)
        self.assertTrue(list(job.glob('run-*.log')))

    def test_cmd_status_entry_handles_unicode_spaces_and_shell_characters(self):
        special = self.target / '目录 with space & ! %'
        special.mkdir()
        job = m.prepare(self.source, special, self.originals)
        command = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
        line = f'"{command}" /d /s /c ""{job / "2-status.cmd"}""'
        result = subprocess.run(line,
                                 input=b'\r\n', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'Planned', result.stdout)

    def test_readonly_file_and_directory_stream_survive(self):
        path = self.source / 'version.txt'
        fs.check(fs.K.SetFileAttributesW(fs.native(path), os.stat(path).st_file_attributes | 1))
        with open(str(self.source / '目录') + ':dir-stream:$DATA', 'wb') as stream:
            stream.write(b'directory ADS')
        job = self.prepare()
        m.apply(job)
        m.mark_verified(job)
        m.retire_original(job)
        m.return_latest(job)
        self.assertTrue(os.stat(path).st_file_attributes & 1)
        with open(str(self.source / '目录') + ':dir-stream:$DATA', 'rb') as stream:
            self.assertEqual(stream.read(), b'directory ADS')

    def test_long_paths_roundtrip(self):
        deep = self.source
        for index in range(5):
            deep = deep / (str(index) + '-' + 'long-name-' * 5)
            os.mkdir(fs.native(deep))
        path = deep / 'payload.txt'
        with open(fs.native(path), 'wb') as stream:
            stream.write(b'long-path-content')
        job = self.prepare()
        m.apply(job)
        m.return_latest(job)
        with open(fs.native(path), 'rb') as stream:
            self.assertEqual(stream.read(), b'long-path-content')

    def test_copied_windows_executable_runs_via_original_path(self):
        command = Path(os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe'))
        fs.copy_file(command, self.source / 'fixture-cmd.exe')
        job = self.prepare()
        m.apply(job)
        process = subprocess.run([str(self.source / 'fixture-cmd.exe'), '/d', '/c', 'exit', '/b', '7'],
                                 capture_output=True)
        self.assertEqual(process.returncode, 7)

    def test_native_process_enumerator_sees_current_python(self):
        self.assertTrue(any(p['pid'] == os.getpid() and p['image'] for p in fs.process_images()))

    def test_optional_second_volume_roundtrip(self):
        destination_parent = os.environ.get('CODEX_MIGRATION_TEST_TARGET_PARENT')
        if not destination_parent:
            self.skipTest('No explicit second-volume test parent supplied')
        with tempfile.TemporaryDirectory(prefix='codex-cross-volume-fixture-',
                                         dir=destination_parent) as other:
            if os.stat(other).st_dev == os.stat(self.source).st_dev:
                self.skipTest('Explicit test parent is on the same volume')
            job = m.prepare(self.source, other, self.originals)
            m.apply(job)
            (self.source / 'newest').write_bytes(b'cross-volume new data')
            m.mark_verified(job)
            m.retire_original(job)
            m.return_latest(job)
            self.assertEqual((self.source / 'newest').read_bytes(), b'cross-volume new data')

    def test_hard_process_exit_releases_locks_and_resumes(self):
        # Separate process, abrupt exit with no Python finally blocks. This
        # fixture-only driver is not a production guard-bypass interface.
        driver = '''
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import migrate as m
job,phase,fixture=Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4])
state=m.read_json(job/'journal.json')
assert fixture.name.startswith('codex-skill-fixture-')
assert Path(state['source']).is_relative_to(fixture)
assert job.is_relative_to(fixture)
m.assert_cold=lambda state: None
def checkpoint(name):
    if name==phase: os._exit(97)
m.FAILPOINT=checkpoint
if phase=='after-unlink-before-return':
    m.return_latest(job)
else:
    m.apply(job)
'''
        for phase in ('copy-entry', 'after-park-before-journal', 'after-unlink-before-return'):
            with self.subTest(phase=phase):
                job = self.prepare()
                if phase == 'after-unlink-before-return':
                    m.apply(job)
                    (self.source / 'hard-exit-latest').write_bytes(b'latest before abrupt exit')
                result = subprocess.run([sys.executable, '-B', '-c', driver,
                                         str(SCRIPTS), str(job), phase, str(self.root)],
                                        capture_output=True)
                self.assertEqual(result.returncode, 97, result.stderr)
                if phase != 'after-unlink-before-return':
                    m.apply(job)
                m.return_latest(job)
                self.assertEqual(self.journal(job)['stage'], 'ReturnedLatest')
                if phase == 'after-unlink-before-return':
                    self.assertEqual((self.source / 'hard-exit-latest').read_bytes(),
                                     b'latest before abrupt exit')


class PlatformGuardTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Only meaningful on non-Windows')
    def test_non_windows_executor_refuses(self):
        with self.assertRaisesRegex(RuntimeError, 'Windows NTFS'):
            fs.require_windows()


if __name__ == '__main__':
    unittest.main()
