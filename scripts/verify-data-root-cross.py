"""Temporary cross-process probe only; never initialize or modify databases."""
import argparse
import ctypes
import getpass
import json
import os
import sys
from pathlib import Path
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['codex', 'windows', 'finish', 'windows-check'])
parser.add_argument('root')
parser.add_argument('token')
args = parser.parse_args()
token = str(uuid.UUID(args.token))
root = Path(args.root)
assert root == Path('C:/Users/USER/GeulbitData')
probe = root / ('.p01-cross-' + token + '.json')

def environment():
    size = ctypes.c_uint(0)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentPackageFullName.argtypes = [ctypes.POINTER(ctypes.c_uint), ctypes.c_wchar_p]
    code = kernel.GetCurrentPackageFullName(ctypes.byref(size), None)
    package = None
    if code == 122:
        buffer = ctypes.create_unicode_buffer(size.value)
        code = kernel.GetCurrentPackageFullName(ctypes.byref(size), buffer)
        package = buffer.value
    return {'actualRoot': str(root.resolve()), 'user': getpass.getuser(), 'pid': os.getpid(),
            'packageCode': code, 'package': package}

if args.mode == 'windows-check':
    import subprocess
    import winreg
    volume = json.loads((root / 'operational' / 'storage.json').read_text())['volumeId']
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, 'GEULBIT_DATA_ROOT', 0, winreg.REG_SZ, str(root))
        winreg.SetValueEx(key, 'GEULBIT_VOLUME_ID', 0, winreg.REG_SZ, volume)
    env = {**os.environ, 'GEULBIT_DATA_ROOT': str(root), 'GEULBIT_VOLUME_ID': volume}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'backend' / 'storage_cli.py'), 'check'], env=env, capture_output=True, text=True)
    receipt = {'environment': environment(), 'exitCode': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}
    (root / 'temp' / '.p01-windows-storage-check.json').write_text(json.dumps(receipt), encoding='utf-8')
    raise SystemExit(result.returncode)
elif args.mode == 'codex':
    root.mkdir()  # Refuse any preexisting directory/data.
    with probe.open('x', encoding='utf-8') as f:
        json.dump({'kind': 'geulbit-p01-cross-probe', 'token': token, 'codex': environment()}, f)
elif args.mode == 'windows':
    data = json.loads(probe.read_text(encoding='utf-8'))
    assert data['kind'] == 'geulbit-p01-cross-probe' and data['token'] == token
    assert data['codex']['actualRoot'].casefold() == str(root).casefold()
    data['windows'] = environment()
    data['windows']['readCodexProbe'] = True
    probe.write_text(json.dumps(data), encoding='utf-8')
else:
    data = json.loads(probe.read_text(encoding='utf-8'))
    assert data['kind'] == 'geulbit-p01-cross-probe' and data['token'] == token
    assert data['windows']['packageCode'] == 15700  # APPMODEL_ERROR_NO_PACKAGE
    assert data['windows']['actualRoot'].casefold() == data['codex']['actualRoot'].casefold() == str(root).casefold()
    assert data['windows']['user'] == data['codex']['user']
    assert data['windows']['readCodexProbe']
    assert list(root.iterdir()) == [probe]  # Preserve unexpected files; never recursive cleanup.
    probe.unlink()
    root.rmdir()
    data['codexReadWindowsResponse'] = True
    data['probeCleaned'] = True
    print(json.dumps(data))
