"""Copy existing restore-verified ciphertext. Never open a DB or decrypt a bundle.

The producer's immutable .verified.json receipt is the completion authority.
Copies use their own lock, bounded streaming I/O, pinned volumes and no-replace
publication. Missing configuration is deliberately a no-op.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid

from .backup_service import MAGIC, LIMIT, SUPPORTED_REVISIONS
from ..storage import windows_volume, StorageBlocked

CHUNK = 1024 * 1024
NAME = re.compile(r'geulbit-\d{8}T\d{6}(?:\d{6})?Z\.gbb\Z')
PARTIAL = re.compile(r'\.geulbit-copy-[a-f0-9]{32}\.partial\Z')
CONFIG = 'external-backup-config.json'


class CopyBlocked(ValueError):
    pass


def checked_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise CopyBlocked('ABSOLUTE_CONTAINED_PATH_REQUIRED')
    for ancestor in [path, *path.parents]:
        if ancestor.is_symlink() or (ancestor.exists() and
                getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise CopyBlocked('REPARSE_PATH_FORBIDDEN')
    if os.path.normcase(str(path.resolve())) != os.path.normcase(os.path.abspath(path)):
        raise CopyBlocked('REDIRECTED_PATH_FORBIDDEN')
    return path


def load_configuration(root):
    path = checked_path(Path(root) / 'operational' / CONFIG)
    if not path.exists():
        return {'version': 1, 'enabled': False, 'approved': False}
    if not path.is_file() or path.stat().st_size > 4096:
        raise CopyBlocked('COPY_CONFIGURATION_INVALID')
    with read_shared(path) as f:
        value = json.loads(f.read(4097))
    if not isinstance(value, dict) or value.get('version') != 1 or type(value.get('enabled')) is not bool:
        raise CopyBlocked('COPY_CONFIGURATION_INVALID')
    return value


@contextmanager
def windows_directory_guard(path):
    # Deny rename/delete of the pinned directory while creating its child file.
    # OPEN_REPARSE_POINT + handle attributes also reject a swapped junction.
    checked_path(path)
    if os.name != 'nt':
        yield
        return
    kernel, handle = _windows_handle(path, 0, 3, 0x02000000 | 0x00200000)
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def _windows_handle(path, access, sharing, flags):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), access, sharing, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    class Information(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
            ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
            ('serial', wintypes.DWORD), ('sizeHigh', wintypes.DWORD), ('sizeLow', wintypes.DWORD),
            ('links', wintypes.DWORD), ('indexHigh', wintypes.DWORD), ('indexLow', wintypes.DWORD)]
    info = Information()
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(Information)]
    if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)) or info.attributes & 0x400:
        kernel.CloseHandle(handle)
        raise CopyBlocked('REPARSE_OR_UNVERIFIED_HANDLE')
    return kernel, handle


@contextmanager
def read_shared(path):
    checked_path(path)
    if os.name == 'nt':
        import msvcrt
        kernel, handle = _windows_handle(path, 0x80000000, 7, 0x00200000)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise CopyBlocked('REGULAR_FILE_REQUIRED')
        yield stream


@contextmanager
def copy_lock(state):
    checked_path(state)
    state.mkdir(exist_ok=True)
    path = checked_path(state / 'copy.lock')
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'\0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise CopyBlocked('COPY_ALREADY_RUNNING') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def signature(s):
    # Python 3.12 Windows path stat retains the historical creation-time ctime,
    # while fstat reports change time. Birth time is the comparable field;
    # byte hashes are independently rechecked before publication.
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns,
            getattr(s, 'st_birthtime_ns', s.st_ctime_ns))


def digest(stream):
    stream.seek(0)
    h, size = hashlib.sha256(), 0
    while block := stream.read(CHUNK):
        size += len(block)
        if size > LIMIT + 1024 * 1024:
            raise CopyBlocked('BACKUP_SIZE_INVALID')
        h.update(block)
    return h.hexdigest(), size


def stream_copy(source, destination):
    source.seek(0)
    size = 0
    while block := source.read(CHUNK):
        size += len(block)
        if size > LIMIT + 1024 * 1024:
            raise CopyBlocked('BACKUP_SIZE_INVALID')
        destination.write(block)


def metadata(archive):
    path = checked_path(archive.with_suffix('.verified.json'))
    if not path.is_file():
        raise CopyBlocked('NO_VERIFIED_RECEIPT')
    with read_shared(path) as f:
        before = signature(os.fstat(f.fileno()))
        data = f.read(4097)
        if len(data) > 4096 or signature(path.stat()) != before:
            raise CopyBlocked('BACKUP_RECEIPT_INVALID')
    try:
        value = json.loads(data)
        when = datetime.fromisoformat(value['createdAt'])
        valid = (value.get('restoreVerified') is True and
                 re.fullmatch('[a-f0-9]{64}', value.get('sha256', '')) and
                 value.get('revision') in SUPPORTED_REVISIONS and when.tzinfo is not None and
                 when <= datetime.now(timezone.utc))
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise CopyBlocked('BACKUP_RECEIPT_INVALID')
    return path, before, data, value


def target_directory(source, config, probe):
    if not isinstance(config.get('targetDirectory'), str) or not config['targetDirectory'].strip():
        raise CopyBlocked('COPY_TARGET_APPROVAL_REQUIRED')
    target = checked_path(config['targetDirectory'])
    identity = config.get('volumeId')
    if config.get('approved') is not True or not isinstance(identity, str) or not identity.strip():
        raise CopyBlocked('COPY_TARGET_APPROVAL_REQUIRED')
    volume = probe(target, health=False)
    root = Path(getattr(volume, 'root', target.anchor))
    if not volume.local or volume.identity.casefold() != identity.casefold():
        raise CopyBlocked('WRONG_OR_UNAVAILABLE_VOLUME')
    if target != root / 'GeulbitBackups':
        raise CopyBlocked('DEDICATED_VOLUME_FOLDER_REQUIRED')
    if probe(source, health=False).identity.casefold() == volume.identity.casefold():
        raise CopyBlocked('SEPARATE_COPY_VOLUME_REQUIRED')
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise CopyBlocked('SOURCE_TARGET_OVERLAP')
    return target


def stable_source(archive, stream, before, receipt_path, receipt_before, receipt_bytes):
    checked_path(archive); checked_path(receipt_path)
    if signature(os.fstat(stream.fileno())) != before or signature(archive.stat()) != before:
        raise CopyBlocked('SOURCE_CHANGED')
    with read_shared(receipt_path) as f:
        if signature(os.fstat(f.fileno())) != receipt_before or f.read(4097) != receipt_bytes:
            raise CopyBlocked('SOURCE_RECEIPT_CHANGED')


def publish(partial, final):
    # Windows rename never replaces an existing file (including on exFAT).
    if os.name == 'nt':
        os.rename(partial, final)
    else:
        os.link(partial, final)
        partial.unlink()


def copy_one(archive, source, config, probe):
    receipt_path, receipt_before, receipt_bytes, value = metadata(archive)
    target = target_directory(source, config, probe)
    target.mkdir(exist_ok=True)
    partial, own_identity = None, None
    with windows_directory_guard(target), read_shared(archive) as original:
        before = signature(os.fstat(original.fileno()))
        if before[2] < len(MAGIC) + 28 or before[2] > LIMIT + 1024 * 1024:
            raise CopyBlocked('BACKUP_SIZE_INVALID')
        if original.read(len(MAGIC)) != MAGIC:
            raise CopyBlocked('ENCRYPTED_BACKUP_REQUIRED')
        expected = (value['sha256'], before[2])
        if digest(original) != expected:
            raise CopyBlocked('SOURCE_HASH_MISMATCH')
        final = checked_path(target / archive.name)
        if final.exists():
            with read_shared(final) as existing:
                if digest(existing) != expected:
                    raise CopyBlocked('EXISTING_COPY_CONFLICT')
            stable_source(archive, original, before, receipt_path, receipt_before, receipt_bytes)
            if digest(original) != expected:
                raise CopyBlocked('SOURCE_CHANGED')
            target_directory(source, config, probe)
            return {'backupId': archive.name, 'sha256': expected[0], 'status': 'ALREADY_PRESENT', 'bytes': expected[1]}
        if shutil.disk_usage(target).free < before[2] + CHUNK:
            raise CopyBlocked('COPY_SPACE_INSUFFICIENT')
        try:
            partial = checked_path(target / ('.geulbit-copy-' + uuid.uuid4().hex + '.partial'))
            with partial.open('xb') as output:
                own_identity = (os.fstat(output.fileno()).st_dev, os.fstat(output.fileno()).st_ino)
                stream_copy(original, output)
                output.flush(); os.fsync(output.fileno())
            with read_shared(partial) as check:
                if digest(check) != expected:
                    raise CopyBlocked('DESTINATION_HASH_MISMATCH')
            stable_source(archive, original, before, receipt_path, receipt_before, receipt_bytes)
            if digest(original) != expected:
                raise CopyBlocked('SOURCE_CHANGED')
            target_directory(source, config, probe)
            publish(partial, final)
            partial = None
            target_directory(source, config, probe)
            with read_shared(final) as check:
                if digest(check) != expected:
                    raise CopyBlocked('PUBLISHED_COPY_UNVERIFIED')
            stable_source(archive, original, before, receipt_path, receipt_before, receipt_bytes)
            return {'backupId': archive.name, 'sha256': expected[0], 'status': 'COPIED', 'bytes': expected[1]}
        finally:
            # Only this invocation's exclusive-created partial, on the still
            # pinned device and with its original file ID, can be removed.
            if partial is not None and own_identity is not None:
                try:
                    target_directory(source, config, probe); checked_path(partial)
                    s = partial.stat()
                    if PARTIAL.fullmatch(partial.name) and (s.st_dev, s.st_ino) == own_identity:
                        partial.unlink()
                except (OSError, ValueError, StorageBlocked):
                    pass  # Unplugged/unknown partial stays untrusted; retry uses a fresh name.


def event(state, record):
    path = checked_path(state / 'events.jsonl')
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps({**record, 'at': datetime.now(timezone.utc).isoformat()}) + '\n')
        f.flush(); os.fsync(f.fileno())


def error_code(error):
    if isinstance(error, CopyBlocked):
        return str(error)
    if isinstance(error, StorageBlocked):
        return error.code
    if isinstance(error, PermissionError):
        return 'COPY_PERMISSION_DENIED'
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return 'COPY_SPACE_INSUFFICIENT'
    return 'COPY_IO_OR_DEVICE_ERROR'


def sync_once(source_directory, config, state_directory, *, probe=windows_volume):
    if config.get('enabled') is not True:
        return {'status': 'DISABLED', 'reason': 'CONFIGURATION_REQUIRED', 'copies': []}
    try:
        source, state = checked_path(source_directory), checked_path(state_directory)
        if not source.is_dir():
            raise CopyBlocked('SOURCE_DIRECTORY_UNAVAILABLE')
        with copy_lock(state):
            copies = []
            for archive in sorted(source.glob('geulbit-*.gbb')):
                if not NAME.fullmatch(archive.name):
                    continue
                try:
                    event(state, {'backupId': archive.name, 'status': 'STARTED'})
                    record = copy_one(archive, source, config, probe)
                except (OSError, ValueError, StorageBlocked) as error:
                    record = {'backupId': archive.name, 'status': 'FAILED', 'errorCode': error_code(error)}
                event(state, record)
                copies.append(record)
            return {'status': 'PARTIAL_FAILURE' if any(r['status'] == 'FAILED' for r in copies) else 'PASS', 'copies': copies}
    except (OSError, ValueError, StorageBlocked) as error:
        return {'status': 'BUSY' if str(error) == 'COPY_ALREADY_RUNNING' else 'BLOCKED',
                'errorCode': error_code(error), 'copies': []}


def dispatch(root, script):
    """No copy/wait on backup or server lifecycle paths; no new daemon/task."""
    try:
        cfg = load_configuration(root)
        if cfg.get('enabled') is not True or cfg.get('approved') is not True:
            return {'status': 'DISABLED'}
        if not cfg.get('volumeId') or not cfg.get('targetDirectory'):
            return {'status': 'CONFIGURATION_REQUIRED'}
        process = subprocess.Popen([sys.executable, str(script), 'sync-external-backups'],
            cwd=Path(script).resolve().parent.parent, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return {'status': 'DISPATCHED', 'pid': process.pid}
    except (OSError, ValueError):
        return {'status': 'DISPATCH_UNAVAILABLE'}
