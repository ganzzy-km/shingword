from __future__ import annotations

import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path


class SafeStorageUnavailable(RuntimeError):
    pass


class SecretStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class DpapiSecretStore:
    """Windows DPAPI CurrentUser 범위의 작은 JSON 비밀 저장소."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.available = os.name == "nt" and hasattr(ctypes, "windll")

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("비밀 값은 비어 있지 않은 문자열이어야 합니다.")
        with self._lock:
            values = self._load()
            values[name] = value
            self._save(values)

    def delete(self, name: str) -> None:
        with self._lock:
            values = self._load()
            if name in values:
                del values[name]
                self._save(values)

    def contains(self, name: str) -> bool:
        try:
            return bool(self.get(name))
        except (SafeStorageUnavailable, SecretStoreError):
            return False

    def _load(self) -> dict[str, str]:
        self._ensure_available()
        if not self.path.exists():
            return {}
        try:
            plaintext = self._unprotect(self.path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items()):
                raise ValueError("invalid payload")
            return payload
        except SafeStorageUnavailable:
            raise
        except Exception as exc:
            raise SecretStoreError("DPAPI 비밀 저장소를 읽을 수 없습니다.") from exc

    def _save(self, values: dict[str, str]) -> None:
        self._ensure_available()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self._protect(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)

    def _ensure_available(self) -> None:
        if not self.available:
            raise SafeStorageUnavailable("Windows DPAPI CurrentUser 저장을 사용할 수 없습니다.")

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    def _protect(self, plaintext: bytes) -> bytes:
        source, source_buffer = self._blob(plaintext)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "글빛 로컬 비밀", None, None, None, 0x1, ctypes.byref(output)
        )
        _ = source_buffer
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def _unprotect(self, ciphertext: bytes) -> bytes:
        source, source_buffer = self._blob(ciphertext)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(output)
        )
        _ = source_buffer
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)


class MemorySecretStore:
    """테스트에서만 사용하는 명시적 메모리 저장소."""

    available = True

    def __init__(self, values: dict[str, str] | None = None):
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)

    def contains(self, name: str) -> bool:
        return name in self.values

