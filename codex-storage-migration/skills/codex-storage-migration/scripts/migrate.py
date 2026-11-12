#!/usr/bin/env python3
"""Recoverable single-directory relocation, Windows fixed local NTFS only.

No arbitrary command execution, antivirus changes, account changes or automatic
rollback. Only operate on an explicitly prepared job. A trusted cold filesystem
is required; this is not a hostile-user/concurrent-reparse security boundary.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import uuid

import windows_fs as fs

SCHEMA = 1
SCRIPT_DIR = Path(__file__).absolute().parent
TOOLS = ('migrate.py', 'windows_fs.py')
FAILPOINT = None  # Test hook, never accepted from environment or command line.


def event(phase, **fields):
    print(json.dumps(dict(phase=phase, **fields), ensure_ascii=True), flush=True)


def checkpoint(phase):
    if FAILPOINT:
        FAILPOINT(phase)


def read_json(path):
    plain(path)
    with open(fs.native(path), encoding='utf-8-sig') as stream:
        return json.load(stream)


def digest(path):
    h = hashlib.sha256()
    with open(fs.native(path), 'rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    plain(path, missing=True)
    plain(path.with_name(path.name + '.previous'), missing=True)
    temporary = path.with_name(path.name + '.next')
    # A stranded journal temp is never an alternate source of instructions.
    if os.path.lexists(fs.native(temporary)):
        plain(temporary)
        if not os.path.isfile(fs.native(temporary)):
            raise RuntimeError('Unexpected journal temporary path')
    with open(fs.native(temporary), 'w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    if exists(path):
        shutil.copyfile(fs.native(path), fs.native(path.with_name(path.name + '.previous')))
    os.replace(fs.native(temporary), fs.native(path))


def path_id(path):
    info = os.lstat(fs.native(path))
    return [info.st_dev, info.st_ino]


def exists(path):
    return os.path.exists(fs.native(path))


def is_directory(path):
    return os.path.isdir(fs.native(path))


def absolute(value):
    path = Path(os.path.abspath(os.path.expanduser(os.fspath(value))))
    if str(path).startswith('\\\\'):
        raise RuntimeError('UNC/device paths are unsupported')
    return path


def under(path, root):
    try:
        return os.path.commonpath([str(path), str(root)]).casefold() == str(root).casefold()
    except ValueError:
        return False


def plain(path, missing=False):
    path = absolute(path)
    for item in reversed((path, *path.parents)):
        try:
            info = os.lstat(fs.native(item))
        except FileNotFoundError:
            if missing:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Unexpected redirect: ' + str(item))
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise RuntimeError('Unexpected hardlinked control/payload file: ' + str(item))
    return path


def inspect_tree(root):
    root = plain(root)
    if not is_directory(root):
        raise RuntimeError('A directory is required')
    pending, entries = [root], []
    while pending:
        path = pending.pop()
        info = os.lstat(fs.native(path))
        attributes = info.st_file_attributes
        # Reject sparse/compressed/EFS/offline/device/recall storage rather than
        # silently changing filesystem semantics or hydrating cloud data.
        if attributes & (0x400 | 0x200 | 0x800 | 0x4000 | 0x1000 | 0x40 | 0x40000 | 0x400000):
            raise RuntimeError('Unsupported link/storage attributes: ' + str(path))
        kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file'
        if kind == 'file' and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise RuntimeError('Special/hardlinked file requires another mechanism: ' + str(path))
        entry = dict(path='.' if path == root else str(path.relative_to(root)), kind=kind,
                     identity=path_id(path), **fs.metadata(path))
        entry['streams'] = {name: dict(size=os.stat(fs.native(str(path) + name)).st_size,
                                       sha256=digest(str(path) + name))
                            for name in fs.stream_names(path)}
        if kind == 'file':
            entry.update(size=info.st_size, sha256=digest(path))
        else:
            with os.scandir(fs.native(path)) as children:
                pending.extend(path / child.name for child in children)
        entries.append(entry)
        if len(entries) % 250 == 0:
            event('snapshot', entries=len(entries))
    return sorted(entries, key=lambda entry: entry['path'])


def comparable(entries, identity=False, ignore_directory_time=False):
    ignored = {'accessed', 'sddl'}
    if not identity:
        ignored.add('identity')
    return [{key: value for key, value in entry.items()
             if key not in ignored and not
             (ignore_directory_time and entry['kind'] == 'directory' and key == 'written')}
            for entry in entries]


def verify(root, expected, identity=False):
    actual = inspect_tree(root)
    if comparable(actual, identity) != comparable(expected, identity):
        a = {entry['path']: entry for entry in comparable(actual, identity)}
        b = {entry['path']: entry for entry in comparable(expected, identity)}
        paths = sorted(path for path in a.keys() | b.keys() if a.get(path) != b.get(path))
        raise RuntimeError('Verification differs at: ' + ', '.join(paths[:8]))
    return actual


def save(job, state):
    state['updated_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    atomic_json(Path(job) / 'journal.json', state)


def load(job):
    fs.require_windows()
    job = plain(job)
    state = read_json(job / 'journal.json')
    if state.get('schema') != SCHEMA or state.get('job') != str(job):
        raise RuntimeError('Journal schema/path binding differs')
    if not re.fullmatch(r'codex-migration-[0-9a-f]{32}', job.name):
        raise RuntimeError('Unexpected job directory name')
    source = absolute(state['source'])
    original_parent = absolute(state['original_parent'])
    expected = dict(active=job / 'active', baseline=job / 'baseline',
                    original=original_parent / (job.name + '-original'),
                    return_tree=original_parent / (job.name + '-return' +
                        ('-' + str(state.get('return_attempt', 0)) if state.get('return_attempt', 0) else '')))
    if not isinstance(state.get('return_attempt', 0), int) or state.get('return_attempt', 0) < 0:
        raise RuntimeError('Invalid return attempt')
    expected_manifest = 'latest' + ('-' + str(state.get('return_attempt', 0))
                                    if state.get('return_attempt', 0) else '')
    if state.get('return_manifest', 'latest') != expected_manifest:
        raise RuntimeError('Return manifest is not bound to its attempt')
    for key, path in expected.items():
        if state.get(key) != str(path):
            raise RuntimeError('Journal contains an unbound path: ' + key)
    if under(job, source) or under(source, job) or under(original_parent, source):
        raise RuntimeError('Overlapping job/source paths')
    if path_id(job) != state['job_identity'] or path_id(original_parent) != state['original_parent_identity']:
        raise RuntimeError('Job or recovery parent identity changed')
    plain(source.parent)
    if path_id(source.parent) != state['source_parent_identity']:
        raise RuntimeError('Source parent identity changed')
    plain(original_parent)
    for name, fingerprint in state['tool_hashes'].items():
        if name not in TOOLS or digest(job / 'tools' / name) != fingerprint:
            raise RuntimeError('Independent recovery code missing or modified: ' + name)
    for key in ('active', 'baseline', 'original', 'return_tree'):
        plain(state[key], missing=True)
    return job, state


@contextmanager
def job_lock(job):
    # Windows file sharing creates a process-scoped exclusive lock. A stale
    # zero-byte lock file is harmless after a crash; the kernel lock is released.
    import ctypes as C
    path = Path(job) / 'operation.lock'
    plain(path, missing=True)
    handle = fs.K.CreateFileW(fs.native(path), 0xC0000000, 0, None, 4, 0x80, None)
    if handle == fs.INVALID:
        raise RuntimeError('Another operation holds this job, or lock access was denied')
    try:
        yield
    finally:
        fs.K.CloseHandle(handle)


def assert_cold(state):
    source = absolute(state['source'])
    for process in fs.process_images():
        image = process['image']
        if process['name'].lower() in state['block_processes'] or (
                image and any(under(absolute(image), absolute(state[key]))
                              for key in ('source', 'original', 'active'))):
            raise RuntimeError('Writer/runtime still running: ' + process['name'])
    # Process enumeration cannot see every script command line or open handle.
    # Caller attestation and file locks remain required; no process is killed.
    for prefix in (sys.executable, sys.prefix, sys.base_prefix):
        if under(absolute(prefix), source):
            raise RuntimeError('Recovery Python depends on the source being moved')


def prepare(source, target_parent, original_parent, kind='data', block_processes=(), pins=()):
    fs.require_windows()
    source, target_parent, original_parent = map(plain, (source, target_parent, original_parent))
    if not all(is_directory(path) for path in (source, target_parent, original_parent)):
        raise RuntimeError('All three paths must be existing ordinary directories')
    if source == Path(source.anchor) or under(target_parent, source) or under(source, target_parent):
        raise RuntimeError('Root or overlapping source/destination refused')
    if under(original_parent, source) or original_parent == source.parent:
        raise RuntimeError('Use a dedicated recovery parent outside source and updater discovery')
    for prefix in (SCRIPT_DIR, sys.executable, sys.prefix, sys.base_prefix):
        if under(absolute(prefix), source):
            raise RuntimeError('Choose a recovery interpreter/toolkit outside the source')
    fs.volume(source)
    fs.volume(target_parent)
    fs.volume(original_parent)
    if path_id(source)[0] != path_id(original_parent)[0]:
        raise RuntimeError('Original parking parent must be on the source volume')
    if kind == 'runtime' and not pins:
        raise RuntimeError('Runtime preparation requires --pin for its executable/version markers')
    markers = {}
    for relative in pins:
        name = Path(relative)
        if name.is_absolute() or name.drive or '..' in name.parts or ':' in relative:
            raise RuntimeError('Runtime marker must be a relative file path')
        file = plain(source / name)
        if not os.path.isfile(fs.native(file)):
            raise RuntimeError('Runtime marker is not an ordinary file')
        markers[str(name)] = digest(file)
    job = target_parent / ('codex-migration-' + uuid.uuid4().hex)
    fs.private_directory(job)
    fs.private_directory(job / 'tools')
    fingerprints = {}
    for name in TOOLS:
        shutil.copyfile(fs.native(SCRIPT_DIR / name), fs.native(job / 'tools' / name))
        fingerprints[name] = digest(job / 'tools' / name)
    blocks = {'codex.exe', 'chatgpt.exe'}
    if kind == 'browser':
        blocks.update(('chrome.exe', 'msedge.exe'))
    blocks.update(name.lower() for name in block_processes)
    state = dict(schema=SCHEMA, stage='Planned', job=str(job), job_identity=path_id(job),
                 source=str(source), source_identity=path_id(source), kind=kind,
                 source_parent_identity=path_id(source.parent),
                 original_parent=str(original_parent),
                 original_parent_identity=path_id(original_parent),
                 active=str(job / 'active'), baseline=str(job / 'baseline'),
                 original=str(original_parent / (job.name + '-original')),
                 return_tree=str(original_parent / (job.name + '-return')),
                 return_attempt=0, return_manifest='latest',
                 block_processes=sorted(blocks), tool_hashes=fingerprints,
                 runtime_markers=markers,
                 application_verified=False, python=str(Path(sys.executable).absolute()))
    save(job, state)
    # BOM-tagged PowerShell preserves a Unicode Python path even when CMD uses
    # a legacy code page. No encoded commands or execution-policy bypass.
    executable = state['python']
    ps = ("param([ValidateSet('apply','status','recover-original','return-latest')][string]$Action='status')\n"
          "$ErrorActionPreference='Stop'\n"
          "$python='" + executable.replace("'", "''") + "'\n"
          "$arguments=@('-B',($PSScriptRoot+'\\tools\\migrate.py'),$Action,'--job',$PSScriptRoot)\n"
          "if($Action -ne 'status'){$arguments+=@('--execute','--writers-stopped')}\n"
          "& $python @arguments\nexit $LASTEXITCODE\n")
    (job / 'Start-Job.ps1').write_text(ps, encoding='utf-8-sig')
    for name, action in [('1-apply', 'apply'), ('2-status', 'status'),
                         ('3-recover-original', 'recover-original'), ('4-return-latest', 'return-latest')]:
        content = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                   'echo Single job only. Close relevant writers. Logs are saved.\r\n'
                   '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
                   '-NoProfile -File "%~dp0Start-Job.ps1" -Action ' + action + '\r\n'
                   'set "result=%errorlevel%"\r\necho EXIT CODE: %result%\r\n'
                   'echo If script policy blocks this entry, use the documented direct Python command.\r\n'
                   'pause\r\nexit /b %result%\r\n')
        (job / (name + '.cmd')).write_bytes(content.encode('ascii'))
    event('prepared', job=str(job), source_changed=False)
    return job


def sealed_manifest(job, name):
    path = Path(job) / (name + '.json')
    seal = Path(job) / (name + '.sha256')
    plain(path)
    plain(seal)
    with open(fs.native(seal), encoding='ascii') as stream:
        seal_value = stream.read().strip()
    if digest(path) != seal_value:
        raise RuntimeError('Manifest seal differs: ' + name)
    entries = read_json(path)
    seen = set()
    for entry in entries:
        relative = entry['path']
        candidate = Path(relative)
        if (relative in seen or candidate.is_absolute() or candidate.drive or
                '..' in candidate.parts or ':' in relative or '\x00' in relative or
                entry['kind'] not in ('file', 'directory')):
            raise RuntimeError('Invalid manifest relative path/type')
        seen.add(relative)
    if '.' not in seen:
        raise RuntimeError('Manifest root entry missing')
    return entries


def write_manifest(job, name, entries):
    path = Path(job) / (name + '.json')
    seal = Path(job) / (name + '.sha256')
    plain(path, missing=True)
    plain(seal, missing=True)
    # A crash can leave the manifest durable before the stage journal. Resume
    # only if the recaptured source is still identical; never silently rebase.
    if exists(path):
        if comparable(read_json(path), identity=True) != comparable(entries, identity=True):
            raise RuntimeError('Captured source changed before stage commit; inspect this job')
        if exists(seal):
            sealed_manifest(job, name)
            return
    else:
        if exists(seal):
            raise RuntimeError('Manifest missing but its seal remains')
        atomic_json(path, entries)
    with open(fs.native(seal), 'x', encoding='ascii') as stream:
        stream.write(digest(path))
        stream.flush()
        os.fsync(stream.fileno())


def copy_tree(source, destination, entries):
    source, destination = plain(source), plain(destination, missing=True)
    allowed = {entry['path'] for entry in entries}
    if exists(destination):
        existing = inspect_tree(destination)
        if any(entry['path'] not in allowed for entry in existing):
            raise RuntimeError('Unexpected entries in a partial copy; preserved')
    else:
        os.mkdir(fs.native(destination))
    # Destination inherits private job permissions until source metadata is set.
    required = 0
    for entry in entries:
        path = destination / entry['path']
        if entry['kind'] == 'file' and not exists(path):
            required += entry['size']
        for suffix, stream in entry['streams'].items():
            if not exists(str(path) + suffix):
                required += stream['size']
    if shutil.disk_usage(fs.native(destination)).free < required:
        raise RuntimeError('Insufficient destination free space for this copy')
    for index, entry in enumerate(sorted(entries, key=lambda item: (item['path'].count('\\'), item['path']))):
        src, dst = source / entry['path'], destination / entry['path']
        plain(src)
        plain(dst, missing=True)
        if entry['kind'] == 'directory':
            if not exists(dst):
                os.mkdir(fs.native(dst))
            if not is_directory(dst):
                raise RuntimeError('Partial-copy type differs')
        elif exists(dst):
            if not os.path.isfile(fs.native(dst)) or digest(dst) != entry['sha256']:
                raise RuntimeError('Incomplete/changed existing payload preserved: ' + str(dst))
        else:
            fs.copy_file(src, dst)
        for suffix, stream in entry['streams'].items():
            target = str(dst) + suffix
            if os.path.exists(fs.native(target)):
                if digest(target) != stream['sha256']:
                    raise RuntimeError('Changed alternate stream preserved')
            else:
                with open(fs.native(str(src) + suffix), 'rb') as incoming:
                    with open(fs.native(target), 'xb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
        checkpoint('copy-entry')
        if (index + 1) % 250 == 0:
            event('copy', destination=str(destination), entries=index + 1, total=len(entries))
    # Children first, then parents; enumeration/copying changes directory times.
    for entry in sorted(entries, key=lambda item: len(Path(item['path']).parts), reverse=True):
        fs.apply_metadata(destination / entry['path'], entry)
    verify(destination, entries)


def exact_portal(source, active):
    info = os.lstat(fs.native(source))
    if getattr(info, 'st_reparse_tag', 0) != 0xA0000003:
        raise RuntimeError('Expected original-path directory junction is absent')
    actual = os.readlink(fs.native(source))
    if actual.startswith('\\\\?\\'):
        actual = actual[4:]
    if absolute(actual) != absolute(active):
        raise RuntimeError('Junction target changed')


def apply(job):
    job, state = load(job)
    with job_lock(job):
        job, state = load(job)
        assert_cold(state)
        source, original = Path(state['source']), Path(state['original'])
        if state['stage'] == 'Planned':
            if path_id(source) != state['source_identity']:
                raise RuntimeError('Source directory generation changed; prepare a new plan')
            for name, fingerprint in state.get('runtime_markers', {}).items():
                relative = Path(name)
                if relative.is_absolute() or relative.drive or '..' in relative.parts or ':' in name:
                    raise RuntimeError('Invalid runtime marker path')
                plain(source / relative)
                if digest(source / relative) != fingerprint:
                    raise RuntimeError('Runtime generation marker changed; revalidate before a new plan')
            event('capture-cold-source', source=str(source))
            entries = inspect_tree(source)
            # All payloads plus peak copies must fit before changing the source.
            need = 2 * sum(entry.get('size', 0) + sum(s['size'] for s in entry['streams'].values())
                           for entry in entries)
            if shutil.disk_usage(job).free < need:
                raise RuntimeError('Insufficient space for active plus baseline copies')
            write_manifest(job, 'manifest', entries)
            checkpoint('manifest-written-before-stage')
            state['stage'] = 'Captured'
            save(job, state)
            checkpoint('captured')
        if state['stage'] == 'Captured':
            entries = sealed_manifest(job, 'manifest')
            locks = fs.lock_files(source, entries, allow_delete=True)
            try:
                verify(source, entries, identity=True)
                for key in ('baseline', 'active'):
                    event('copy-and-verify', unit=key)
                    copy_tree(source, state[key], entries)
                    checkpoint(key + '-verified')
                verify(source, entries, identity=True)
            finally:
                fs.unlock(locks)
            state['stage'] = 'CopiesVerified'
            save(job, state)
        if state['stage'] == 'CopiesVerified':
            entries = sealed_manifest(job, 'manifest')
            verify(state['baseline'], entries)
            verify(state['active'], entries)
            if exists(source):
                plain(source)
                if os.path.lexists(fs.native(original)):
                    raise RuntimeError('Unexpected parked original already exists')
                verify(source, entries, identity=True)
                assert_cold(state)
                os.rename(fs.native(source), fs.native(original))
                checkpoint('after-park-before-journal')
            else:
                # Reconcile a crash immediately after the atomic rename.
                verify(original, entries, identity=True)
            state['stage'] = 'Parked'
            save(job, state)
            checkpoint('parked')
        if state['stage'] == 'Parked':
            entries = sealed_manifest(job, 'manifest')
            verify(original, entries, identity=True)
            verify(state['baseline'], entries)
            verify(state['active'], entries)
            assert_cold(state)
            if os.path.lexists(fs.native(source)):
                exact_portal(source, state['active'])
            else:
                fs.junction(source, state['active'])
                checkpoint('after-link-before-journal')
            state['stage'] = 'Linked'
            save(job, state)
        if state['stage'] not in ('Linked', 'ApplicationVerified', 'SourceRetired'):
            raise RuntimeError('Cannot apply from stage ' + state['stage'])
        exact_portal(source, state['active'])
        event('PASS', stage=state['stage'], application_tested=state['application_verified'],
              source_original_retained=exists(state['original']))


def recover_original(job):
    job, state = load(job)
    with job_lock(job):
        job, state = load(job)
        assert_cold(state)
        if state['stage'] not in ('CopiesVerified', 'Parked'):
            raise RuntimeError('This action only restores an unlinked intact parked source')
        if os.path.lexists(fs.native(state['source'])):
            raise RuntimeError('Source exists; preserved without overwrite. Inspect actual state.')
        entries = sealed_manifest(job, 'manifest')
        verify(state['original'], entries, identity=True)
        os.rename(fs.native(state['original']), fs.native(state['source']))
        state['stage'] = 'RecoveredOriginal'
        save(job, state)
        event('PASS', stage=state['stage'], all_destination_copies_retained=True)


def mark_verified(job):
    job, state = load(job)
    with job_lock(job):
        job, state = load(job)
        if state['stage'] not in ('Linked', 'ApplicationVerified'):
            raise RuntimeError('Only a linked unit can be marked application verified')
        exact_portal(state['source'], state['active'])
        entries = sealed_manifest(job, 'manifest')
        verify(state['baseline'], entries)
        verify(state['original'], entries, identity=True)
        state.update(stage='ApplicationVerified', application_verified=True)
        save(job, state)
        event('PASS', verification='caller attestation; not an automated application test')


def retire_original(job):
    job, state = load(job)
    with job_lock(job):
        job, state = load(job)
        assert_cold(state)
        if state['stage'] not in ('ApplicationVerified', 'RetiringOriginal'):
            raise RuntimeError('Application verification is required before source retirement')
        exact_portal(state['source'], state['active'])
        entries = sealed_manifest(job, 'manifest')
        verify(state['baseline'], entries)
        inspect_tree(state['active'])
        original = Path(state['original'])
        if state['stage'] == 'ApplicationVerified':
            verify(original, entries, identity=True)
            state['stage'] = 'RetiringOriginal'
            save(job, state)
        # Deletion is limited to exact manifest identities. Never recurse over
        # arbitrary discovered content. A partial retirement is resumable.
        locks = fs.lock_files(state['baseline'], entries)
        try:
            for entry in sorted(entries, key=lambda item: (len(Path(item['path']).parts),
                                                          item['kind'] == 'file'), reverse=True):
                path = original / entry['path']
                if not os.path.lexists(fs.native(path)):
                    continue
                plain(path)
                if path_id(path) != entry['identity']:
                    raise RuntimeError('Original record identity changed; deletion refused')
                if entry['kind'] == 'file':
                    current = inspect_file(path, entry)
                    if not current:
                        raise RuntimeError('Original contents changed; deletion refused')
                    fs.check(fs.K.SetFileAttributesW(fs.native(path), entry['attributes'] & ~1))
                    os.unlink(fs.native(path))
                else:
                    current = fs.metadata(path)
                    if current['access'] != entry['access'] or not streams_match(path, entry):
                        raise RuntimeError('Original directory metadata/streams changed; deletion refused')
                    os.rmdir(fs.native(path))  # refuses unexpected child content
                checkpoint('retire-entry')
        finally:
            fs.unlock(locks)
        state['stage'] = 'SourceRetired'
        save(job, state)
        event('PASS', stage=state['stage'], backup=str(state['baseline']))


def inspect_file(path, entry):
    if digest(path) != entry['sha256'] or fs.descriptor(path)['access'] != entry['access']:
        return False
    return streams_match(path, entry)


def streams_match(path, entry):
    if fs.stream_names(path) != sorted(entry['streams']):
        return False
    return all(digest(str(path) + name) == value['sha256']
               for name, value in entry['streams'].items())


def restart_return(job):
    job, state = load(job)
    with job_lock(job):
        job, state = load(job)
        assert_cold(state)
        if state['stage'] not in ('ReturningLatest', 'ReturnReady'):
            raise RuntimeError('Only a pending return with its portal intact can restart')
        exact_portal(state['source'], state['active'])
        attempt = state.get('return_attempt', 0) + 1
        name = 'latest-' + str(attempt)
        entries = inspect_tree(state['active'])
        write_manifest(job, name, entries)
        old = state['return_tree']
        state.update(return_attempt=attempt, return_manifest=name,
                     return_tree=str(Path(state['original_parent']) / (job.name + '-return-' + str(attempt))),
                     stage='ReturningLatest')
        save(job, state)
        event('return-restarted', previous_staging_preserved=old,
              next_action='return-latest')


def return_latest(job):
    job, state = load(job)
    with job_lock(job):
        job, state = load(job)
        assert_cold(state)
        if state['stage'] in ('Linked', 'ApplicationVerified', 'SourceRetired', 'RetiringOriginal'):
            exact_portal(state['source'], state['active'])
            entries = inspect_tree(state['active'])
            write_manifest(job, state.get('return_manifest', 'latest'), entries)
            state['stage'] = 'ReturningLatest'
            save(job, state)
            checkpoint('latest-captured')
        if state['stage'] == 'ReturningLatest':
            entries = sealed_manifest(job, state.get('return_manifest', 'latest'))
            exact_portal(state['source'], state['active'])
            locks = fs.lock_files(state['active'], entries)
            try:
                verify(state['active'], entries, identity=True)
                copy_tree(state['active'], state['return_tree'], entries)
                verify(state['active'], entries, identity=True)
            finally:
                fs.unlock(locks)
            state['return_identity'] = path_id(state['return_tree'])
            state['stage'] = 'ReturnReady'
            save(job, state)
            checkpoint('return-ready')
        if state['stage'] == 'ReturnReady':
            entries = sealed_manifest(job, state.get('return_manifest', 'latest'))
            verify(state['active'], entries, identity=True)
            source, stage = Path(state['source']), Path(state['return_tree'])
            if os.path.lexists(fs.native(stage)):
                verify(stage, entries)
                if path_id(stage) != state['return_identity']:
                    raise RuntimeError('Return staging identity changed')
                if os.path.lexists(fs.native(source)):
                    exact_portal(source, state['active'])
                    verify(state['active'], entries, identity=True)
                    os.rmdir(fs.native(source))  # remove only the exact junction
                    checkpoint('after-unlink-before-return')
                os.rename(fs.native(stage), fs.native(source))
                checkpoint('after-return-before-journal')
            if path_id(source) != state['return_identity']:
                raise RuntimeError('Unexpected ordinary source preserved')
            verify(source, entries)
            state['stage'] = 'ReturnedLatest'
            save(job, state)
        if state['stage'] != 'ReturnedLatest':
            raise RuntimeError('Cannot return from stage ' + state['stage'])
        event('PASS', stage=state['stage'], destination_data_retained=True)


def status(job):
    job, state = load(job)
    result = {key: state[key] for key in ('stage', 'source', 'active', 'baseline',
                                         'original', 'application_verified')}
    result['source_exists'] = os.path.lexists(fs.native(state['source']))
    result['original_exists'] = os.path.lexists(fs.native(state['original']))
    result['actual_portal_matches'] = False
    try:
        exact_portal(state['source'], state['active'])
        result['actual_portal_matches'] = True
    except OSError:
        pass
    except RuntimeError:
        pass
    event('status', **result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'apply', 'status', 'recover-original',
                                          'mark-verified', 'retire-original', 'return-latest',
                                          'restart-return'))
    parser.add_argument('--source')
    parser.add_argument('--target-parent')
    parser.add_argument('--original-parent')
    parser.add_argument('--kind', choices=('data', 'runtime', 'browser', 'sqlite'), default='data')
    parser.add_argument('--block-process', action='append', default=[])
    parser.add_argument('--pin', action='append', default=[], help='Relative executable/version marker file')
    parser.add_argument('--job')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--writers-stopped', action='store_true')
    parser.add_argument('--application-verified', action='store_true')
    args = parser.parse_args()
    if args.action == 'prepare':
        if not all((args.source, args.target_parent, args.original_parent)):
            parser.error('prepare requires --source, --target-parent, --original-parent')
        prepare(args.source, args.target_parent, args.original_parent, args.kind,
                args.block_process, args.pin)
        return 0
    if not args.job:
        parser.error('--job is required')
    if args.action != 'status' and not args.execute:
        parser.error('Mutation requires --execute')
    if args.action not in ('status', 'mark-verified') and not args.writers_stopped:
        parser.error('Stop all relevant writers, then pass --writers-stopped')
    if args.action == 'mark-verified' and not args.application_verified:
        parser.error('Confirm actual relevant use after restart with --application-verified')
    # Each independent invocation keeps its own append-only human-readable log.
    job, _ = load(args.job)
    log = job / ('run-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6] + '.log')
    class Tee:
        def __init__(self, terminal, stream):
            self.terminal, self.stream = terminal, stream
        def write(self, value):
            self.terminal.write(value)
            self.stream.write(value)
        def flush(self):
            self.terminal.flush()
            self.stream.flush()
    with open(fs.native(log), 'x', encoding='utf-8') as stream:
        original_stdout = sys.stdout
        sys.stdout = Tee(original_stdout, stream)
        try:
            {'apply': apply, 'status': status, 'recover-original': recover_original,
             'mark-verified': mark_verified, 'retire-original': retire_original,
             'return-latest': return_latest, 'restart-return': restart_return}[args.action](job)
        except Exception as error:
            event('FAILED', error=str(error), automatic_reverse_attempted=False)
            return 23
        finally:
            sys.stdout = original_stdout
            print('LOG: ' + str(log), flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        event('FAILED', error=str(error), automatic_reverse_attempted=False)
        sys.exit(23)
