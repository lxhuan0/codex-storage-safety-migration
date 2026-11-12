"""Windows-only NTFS primitives; no background services or security exceptions."""
import base64
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import struct

if os.name == 'nt':
    K = C.WinDLL('kernel32', use_last_error=True)
    A = C.WinDLL('advapi32', use_last_error=True)
    INVALID = C.c_void_p(-1).value
    K.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p,
                              W.DWORD, W.DWORD, W.HANDLE]
    K.CreateFileW.restype = W.HANDLE
    K.CloseHandle.argtypes = [W.HANDLE]
    K.FindClose.argtypes = [W.HANDLE]
    K.FindFirstStreamW.argtypes = [W.LPCWSTR, W.DWORD, C.c_void_p, W.DWORD]
    K.FindFirstStreamW.restype = W.HANDLE
    K.FindNextStreamW.argtypes = [W.HANDLE, C.c_void_p]
    K.DeviceIoControl.argtypes = [W.HANDLE, W.DWORD, C.c_void_p, W.DWORD,
                                 C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
    A.GetFileSecurityW.argtypes = [W.LPCWSTR, W.DWORD, C.c_void_p, W.DWORD,
                                   C.POINTER(W.DWORD)]
    A.SetFileSecurityW.argtypes = [W.LPCWSTR, W.DWORD, C.c_void_p]
    A.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        C.c_void_p, W.DWORD, W.DWORD, C.POINTER(W.LPWSTR), C.POINTER(W.DWORD)]
    A.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.POINTER(W.DWORD)]
    A.GetSecurityDescriptorDacl.argtypes = [C.c_void_p, C.POINTER(W.BOOL),
                                          C.POINTER(C.c_void_p), C.POINTER(W.BOOL)]
    K.LocalFree.argtypes = [C.c_void_p]
    K.SetFileAttributesW.argtypes = [W.LPCWSTR, W.DWORD]
    K.CopyFileW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.BOOL]
    K.GetVolumePathNameW.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD]
    K.GetVolumeInformationW.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD,
                                      C.c_void_p, C.c_void_p, C.c_void_p,
                                      W.LPWSTR, W.DWORD]
    K.GetDriveTypeW.argtypes = [W.LPCWSTR]


def require_windows():
    if os.name != 'nt':
        raise RuntimeError('Execution backend supports Windows NTFS only')


def native(path):
    value = os.fspath(path)
    if value.startswith('\\\\?\\'):
        return value
    if value.startswith('\\\\'):
        raise RuntimeError('Network paths are not supported by this executor')
    return '\\\\?\\' + os.path.abspath(value)


def check(ok):
    if not ok:
        raise C.WinError(C.get_last_error())


def open_handle(path, access=0x80, share=7):
    handle = K.CreateFileW(native(path), access, share, None, 3, 0x02000000, None)
    if handle == INVALID:
        raise C.WinError(C.get_last_error())
    return handle


def volume(path):
    require_windows()
    buffer = C.create_unicode_buffer(32768)
    check(K.GetVolumePathNameW(native(path), buffer, len(buffer)))
    fs = C.create_unicode_buffer(256)
    check(K.GetVolumeInformationW(buffer.value, None, 0, None, None, None, fs, len(fs)))
    if fs.value != 'NTFS' or K.GetDriveTypeW(buffer.value) != 3:
        raise RuntimeError('Executor requires a fixed local NTFS volume: ' + str(path))
    return buffer.value


def descriptor(path):
    needed = W.DWORD()
    A.GetFileSecurityW(native(path), 7, None, 0, C.byref(needed))
    if not needed.value:
        raise C.WinError(C.get_last_error())
    raw = C.create_string_buffer(needed.value)
    check(A.GetFileSecurityW(native(path), 7, raw, len(raw), C.byref(needed)))
    text = W.LPWSTR()
    check(A.ConvertSecurityDescriptorToStringSecurityDescriptorW(raw, 1, 7,
                                                                C.byref(text), None))
    try:
        sddl = text.value
    finally:
        K.LocalFree(C.cast(text, C.c_void_p))
    # Preserve effective ACE bytes and order. Inherited-vs-explicit origin may
    # change when protecting the copy from its new parent's inheritance.
    present, defaulted, acl = W.BOOL(), W.BOOL(), C.c_void_p()
    check(A.GetSecurityDescriptorDacl(raw, C.byref(present), C.byref(acl),
                                      C.byref(defaulted)))
    if not present.value or not acl.value:
        raise RuntimeError('Null or absent DACL refused')
    header = C.string_at(acl, 8)
    count = struct.unpack_from('<H', header, 4)[0]
    if not count:
        raise RuntimeError('Empty DACL requires manual review')
    entries, offset = [], 8
    for _ in range(count):
        head = C.string_at(acl.value + offset, 4)
        length = struct.unpack_from('<H', head, 2)[0]
        data = bytearray(C.string_at(acl.value + offset, length))
        data[1] &= ~0x10
        entries.append(base64.b64encode(data).decode('ascii'))
        offset += length
    identity = sddl.split('D:', 1)[0]
    return dict(sddl=sddl, access=dict(identity=identity, aces=entries))


def set_security(path, sddl):
    pointer = C.c_void_p()
    check(A.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1,
                                                                C.byref(pointer), None))
    try:
        # Copies use protected DACLs so destination-parent permissions cannot
        # silently grant new access. Original source descriptors are untouched.
        check(A.SetFileSecurityW(native(path), 0x80000007, pointer))
    finally:
        K.LocalFree(pointer)


def private_directory(path):
    # Owner Rights + SYSTEM, protected. Creator remains owner. No global ACL edits.
    import subprocess
    output = subprocess.check_output(['whoami.exe', '/user', '/fo', 'csv', '/nh'],
                                     text=True, errors='replace')
    import re
    match = re.search(r'S-1-5-21-[0-9-]+', output)
    if not match:
        raise RuntimeError('Cannot establish current interactive user SID')
    sid = match.group(0)
    os.mkdir(native(path))
    set_security(path, f'O:{sid}G:{sid}D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)')


def metadata(path):
    handle = open_handle(path)
    creation, access, write = C.c_ulonglong(), C.c_ulonglong(), C.c_ulonglong()
    K.GetFileTime.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_void_p]
    try:
        check(K.GetFileTime(handle, C.byref(creation), C.byref(access), C.byref(write)))
    finally:
        K.CloseHandle(handle)
    info = os.lstat(native(path))
    security = descriptor(path)
    return dict(created=creation.value, accessed=access.value, written=write.value,
                attributes=info.st_file_attributes, sddl=security['sddl'],
                access=security['access'])


def apply_metadata(path, entry):
    # File writes may be blocked by readonly; normalize only our new copy.
    check(K.SetFileAttributesW(native(path), entry['attributes'] & ~1))
    set_security(path, entry['sddl'])
    handle = open_handle(path, 0x100)
    creation = C.c_ulonglong(entry['created'])
    access = C.c_ulonglong(entry['accessed'])
    write = C.c_ulonglong(entry['written'])
    K.SetFileTime.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_void_p]
    try:
        check(K.SetFileTime(handle, C.byref(creation), C.byref(access), C.byref(write)))
    finally:
        K.CloseHandle(handle)
    check(K.SetFileAttributesW(native(path), entry['attributes']))


class StreamData(C.Structure):
    _fields_ = [('size', C.c_longlong), ('name', C.c_wchar * 296)]


def stream_names(path):
    data = StreamData()
    handle = K.FindFirstStreamW(native(path), 0, C.byref(data), 0)
    if handle == INVALID:
        if C.get_last_error() == 38:
            return []
        raise C.WinError(C.get_last_error())
    result = []
    try:
        while True:
            name = data.name
            if name != '::$DATA':
                if not name.startswith(':') or not name.endswith(':$DATA'):
                    raise RuntimeError('Unknown alternate stream syntax')
                result.append(name)
            if not K.FindNextStreamW(handle, C.byref(data)):
                if C.get_last_error() != 38:
                    raise C.WinError(C.get_last_error())
                break
    finally:
        K.FindClose(handle)
    return sorted(result)


def copy_file(source, target):
    check(K.CopyFileW(native(source), native(target), True))


def junction(link, target):
    os.mkdir(native(link))
    handle = None
    try:
        handle = K.CreateFileW(native(link), 0x40000000, 0, None, 3,
                              0x02200000, None)
        if handle == INVALID:
            handle = None
            raise C.WinError(C.get_last_error())
        substitute = ('\\??\\' + str(target)).encode('utf-16-le')
        display = str(target).encode('utf-16-le')
        data = substitute + b'\0\0' + display + b'\0\0'
        packet = struct.pack('<IHHHHHH', 0xA0000003, len(data) + 8, 0,
                             0, len(substitute), len(substitute) + 2, len(display)) + data
        buffer = C.create_string_buffer(packet)
        returned = W.DWORD()
        check(K.DeviceIoControl(handle, 0x900A4, buffer, len(packet), None, 0,
                                C.byref(returned), None))
    except BaseException:
        if handle is not None:
            K.CloseHandle(handle)
            handle = None
        # Only an empty directory created by this call; never recursive removal.
        if not os.path.islink(native(link)):
            try:
                os.rmdir(native(link))
            except OSError:
                pass
        raise
    finally:
        if handle is not None:
            K.CloseHandle(handle)


def lock_files(root, entries, allow_delete=False):
    handles = []
    try:
        for entry in entries:
            if entry['kind'] == 'file':
                path = Path(root) / entry['path']
                for suffix in [''] + list(entry['streams']):
                    handles.append(open_handle(str(path) + suffix, 0x80000000,
                                               1 | (4 if allow_delete else 0)))
        return handles
    except BaseException:
        unlock(handles)
        raise


def unlock(handles):
    for handle in handles:
        K.CloseHandle(handle)


def process_images():
    class Entry(C.Structure):
        _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD),
                    ('heap', C.c_size_t), ('module', W.DWORD), ('threads', W.DWORD),
                    ('parent', W.DWORD), ('priority', W.LONG), ('flags', W.DWORD),
                    ('exe', C.c_wchar * 260)]
    K.CreateToolhelp32Snapshot.restype = W.HANDLE
    K.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(Entry)]
    K.Process32NextW.argtypes = [W.HANDLE, C.POINTER(Entry)]
    K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    K.OpenProcess.restype = W.HANDLE
    K.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR,
                                           C.POINTER(W.DWORD)]
    snapshot = K.CreateToolhelp32Snapshot(2, 0)
    if snapshot == INVALID:
        raise C.WinError(C.get_last_error())
    entry = Entry()
    entry.size = C.sizeof(entry)
    result = []
    try:
        ok = K.Process32FirstW(snapshot, C.byref(entry))
        while ok:
            image = None
            handle = K.OpenProcess(0x1000, False, entry.pid)
            if handle:
                try:
                    text, length = C.create_unicode_buffer(32768), W.DWORD(32768)
                    if K.QueryFullProcessImageNameW(handle, 0, text, C.byref(length)):
                        image = text.value
                finally:
                    K.CloseHandle(handle)
            result.append(dict(pid=entry.pid, name=entry.exe, image=image))
            ok = K.Process32NextW(snapshot, C.byref(entry))
    finally:
        K.CloseHandle(snapshot)
    return result
