"""Fail-closed local storage boundary. No initialization on ordinary startup."""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import sqlite3
import subprocess
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

SCHEMA_HEAD = "0005_writing_tools"


class StorageBlocked(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Volume:
    identity: str
    filesystem: str
    local: bool
    healthy: bool


def windows_volume(root: Path, *, health=True) -> Volume:
    if os.name != "nt" or not root.drive or root.drive.startswith("\\\\"):
        raise StorageBlocked("LOCAL_WINDOWS_VOLUME_REQUIRED")
    anchor = root.anchor
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # Specify wide-string signatures: implicit pointer conversion is unsafe.
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kind = kernel.GetDriveTypeW(anchor)
    if kind not in (2, 3):
        raise StorageBlocked("VOLUME_UNAVAILABLE")
    name, fs, identity = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
    serial, maximum, flags = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    kernel.GetVolumeInformationW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.c_wchar_p, ctypes.c_ulong]
    kernel.GetVolumeNameForVolumeMountPointW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    if not kernel.GetVolumeInformationW(anchor, name, 261, ctypes.byref(serial), ctypes.byref(maximum), ctypes.byref(flags), fs, 261):
        raise StorageBlocked("VOLUME_UNAVAILABLE")
    if not kernel.GetVolumeNameForVolumeMountPointW(anchor, identity, 261):
        raise StorageBlocked("VOLUME_ID_UNAVAILABLE")
    healthy = True
    if health:
        letter = root.drive[0]
        if not letter.isalpha():
            raise StorageBlocked("INVALID_DATA_ROOT")
        try:
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"(Get-Volume -DriveLetter {letter} -ErrorAction Stop).HealthStatus.ToString()"], capture_output=True, text=True, timeout=15, check=True)
            healthy = result.stdout.strip() == "Healthy"
        except (OSError, subprocess.SubprocessError):
            raise StorageBlocked("VOLUME_HEALTH_UNVERIFIED") from None
    return Volume(identity.value, fs.value, True, healthy)


def validate_volume(root, expected_id, probe=windows_volume, *, health=True):
    if not isinstance(root, Path):
        root = Path(root)
    if not root.is_absolute() or root == Path(root.anchor) or ".." in root.parts:
        raise StorageBlocked("INVALID_DATA_ROOT")
    if not expected_id:
        raise StorageBlocked("VOLUME_ID_REQUIRED")
    volume = probe(root, health=health)
    if volume.identity.casefold() != expected_id.casefold():
        raise StorageBlocked("WRONG_VOLUME")
    if not volume.local or volume.filesystem.upper() != "NTFS":
        raise StorageBlocked("UNSUPPORTED_FILESYSTEM")
    if not volume.healthy:
        raise StorageBlocked("UNHEALTHY_VOLUME")
    ancestor = root
    while ancestor != Path(ancestor.anchor):
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise StorageBlocked("REPARSE_PATH_FORBIDDEN")
        ancestor = ancestor.parent
    # Packaged Windows hosts may silently virtualize AppData without a junction.
    # Never accept a different physical directory as the approved Data Root.
    if os.path.normcase(str(root.resolve())) != os.path.normcase(os.path.abspath(root)):
        raise StorageBlocked("DATA_ROOT_REDIRECTED")
    return volume


def contained(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise StorageBlocked("PATH_OUTSIDE_DATA_ROOT")
    return path


def db_path(root):
    return contained(root, Path(root) / "db" / "geulbit.sqlite3")


def check_database(path, *, writable=False):
    if not Path(path).is_file():
        raise StorageBlocked("DATABASE_MISSING")
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise StorageBlocked("DATABASE_CORRUPT")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise StorageBlocked("FOREIGN_KEY_VIOLATION")
            if connection.execute("SELECT version_num FROM alembic_version").fetchall() != [(SCHEMA_HEAD,)]:
                raise StorageBlocked("MIGRATION_REQUIRED")
            if connection.execute("PRAGMA journal_mode").fetchone() != ("wal",):
                raise StorageBlocked("WAL_REQUIRED")
        if writable:
            with closing(sqlite3.connect(Path(path).as_uri() + "?mode=rw", uri=True)) as connection:
                connection.execute("PRAGMA busy_timeout=5000")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("ROLLBACK")
    except sqlite3.Error:
        raise StorageBlocked("DATABASE_STATE_UNVERIFIED") from None


def storage_paths(root):
    return {"DATABASE_PATH": db_path(root), "UPLOAD_FOLDER": contained(root, root / "files"), "TEMP_FOLDER": contained(root, root / "temp"), "BACKUP_FOLDER": contained(root, root / "operational" / "backups"), "SECRET_FILE": contained(root, root / "operational" / "secrets.dat"), "ADMIN_STATE_FILE": contained(root, root / "operational" / "local-admin.json"), "ADMIN_AUDIT_FILE": contained(root, root / "operational" / "local-admin-audit.jsonl")}


class StorageGuard:
    def __init__(self, root, expected_id, probe=windows_volume):
        self.root = Path(root)
        self.expected_id, self.probe = expected_id, probe
        self.blocked = None
        self.lock = threading.RLock()

    def check(self, *, startup=False):
        with self.lock:
            if self.blocked:
                raise StorageBlocked(self.blocked)
            try:
                validate_volume(self.root, self.expected_id, self.probe, health=startup)
                paths = storage_paths(self.root)
                manifest = contained(self.root, self.root / "operational" / "storage.json")
                if (self.root / ".initializing").exists() or not manifest.is_file():
                    raise StorageBlocked("EXPLICIT_INITIALIZATION_REQUIRED")
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if data.get("volumeId", "").casefold() != self.expected_id.casefold() or data.get("root") != str(self.root):
                    raise StorageBlocked("STORAGE_IDENTITY_MISMATCH")
                if not paths["DATABASE_PATH"].is_file():
                    raise StorageBlocked("DATABASE_MISSING")
                for key in ("UPLOAD_FOLDER", "TEMP_FOLDER", "BACKUP_FOLDER"):
                    if not paths[key].is_dir():
                        raise StorageBlocked("STORAGE_DIRECTORY_MISSING")
                if startup:
                    check_database(paths["DATABASE_PATH"], writable=True)
                    if shutil.disk_usage(self.root).free < 64 * 1024 * 1024:
                        raise StorageBlocked("INSUFFICIENT_STORAGE_SPACE")
                return paths
            except StorageBlocked as exc:
                self.blocked = exc.code
                raise
            except (OSError, ValueError, TypeError, AttributeError):
                self.blocked = "STORAGE_UNAVAILABLE"
                raise StorageBlocked(self.blocked) from None

    def latch(self, code="STORAGE_IO_FAILURE"):
        with self.lock:
            self.blocked = code


def configure_storage(app):
    # Synthetic fixtures must provide explicit paths; no TESTING fallback DB.
    if app.config.get("TESTING"):
        for key in ("DATABASE_PATH", "UPLOAD_FOLDER", "BACKUP_FOLDER"):
            if not app.config.get(key):
                raise StorageBlocked("EXPLICIT_TEST_PATHS_REQUIRED")
        app.config.setdefault("TEMP_FOLDER", Path(app.config["DATABASE_PATH"]).parent / "temp")
        if app.config["TEMP_FOLDER"] is None:
            app.config["TEMP_FOLDER"] = Path(app.config["DATABASE_PATH"]).parent / "temp"
        for key in ("DATABASE_PATH", "UPLOAD_FOLDER", "BACKUP_FOLDER", "TEMP_FOLDER"):
            path = Path(app.config[key])
            (path.parent if key == "DATABASE_PATH" else path).mkdir(parents=True, exist_ok=True)
        for key, name in (("SECRET_FILE", "secrets.dat"), ("ADMIN_STATE_FILE", "local-admin.json"), ("ADMIN_AUDIT_FILE", "local-admin-audit.jsonl")):
            if app.config.get(key) is None:
                app.config[key] = Path(app.config["DATABASE_PATH"]).parent / name
        return None
    root = app.config.get("DATA_ROOT")
    if not root:
        raise StorageBlocked("DATA_ROOT_REQUIRED")
    guard = StorageGuard(root, app.config.get("VOLUME_ID"))
    paths = guard.check(startup=True)
    app.config.update(paths)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + paths["DATABASE_PATH"].as_uri() + "?mode=rw&uri=true"
    app.extensions["storage_guard"] = guard
    return guard


def initialize_storage(root, expected_id, probe=windows_volume):
    """Explicit CLI only; refuse existing data and retain failed-init evidence."""
    root = Path(root)
    volume = validate_volume(root, expected_id, probe)
    if root.exists():
        raise StorageBlocked("EXISTING_DATA_ROOT")
    if not root.parent.is_dir() or shutil.disk_usage(root.parent).free < 64 * 1024 * 1024:
        raise StorageBlocked("PARENT_OR_SPACE_UNAVAILABLE")
    root.mkdir()  # Never exist_ok: competing initializers cannot overwrite.
    marker = root / ".initializing"
    marker.write_text("initialization in progress", encoding="utf-8")
    paths = storage_paths(root)
    for key in ("DATABASE_PATH", "UPLOAD_FOLDER", "TEMP_FOLDER", "BACKUP_FOLDER"):
        (paths[key].parent if key == "DATABASE_PATH" else paths[key]).mkdir(parents=True, exist_ok=True)
    from flask import Flask
    from flask_migrate import upgrade
    from .extensions import db, migrate
    from . import models  # noqa: F401
    from .seed import ensure_defaults
    app = Flask("geulbit-storage-initialization")
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///" + paths["DATABASE_PATH"].as_posix(), SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    directory = str(Path(__file__).resolve().parents[1] / "migrations")
    migrate.init_app(app, db, directory=directory)
    with app.app_context():
        upgrade(directory=directory)
        ensure_defaults()
        db.session.remove()
        db.engine.dispose()
    check_database(paths["DATABASE_PATH"])
    validate_volume(root, expected_id, probe)
    manifest = root / "operational" / "storage.json"
    with manifest.open("x", encoding="utf-8") as target:
        json.dump({"root": str(root), "volumeId": volume.identity, "filesystem": volume.filesystem, "schemaHead": SCHEMA_HEAD}, target)
    marker.unlink()
    return paths
