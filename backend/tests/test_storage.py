import hashlib
import io
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.services.secrets_service import MemorySecretStore
from app.storage import StorageBlocked, StorageGuard, Volume, check_database, initialize_storage, validate_volume


IDENTITY = "synthetic-volume-only"


def healthy(_root, **_kwargs):
    return Volume(IDENTITY, "NTFS", True, True)


def test_explicit_initialization_uses_existing_alembic_and_sqlite_constraints(tmp_path):
    root = tmp_path / "data"
    paths = initialize_storage(root, IDENTITY, healthy)
    assert not (root / ".initializing").exists()
    assert StorageGuard(root, IDENTITY, healthy).check(startup=True) == paths
    with sqlite3.connect(paths["DATABASE_PATH"]) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        from app.storage import SCHEMA_HEAD
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (SCHEMA_HEAD,)
    app = create_app({"TESTING": True, **paths, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + paths["DATABASE_PATH"].as_posix(), "SECRET_STORE": MemorySecretStore()})
    with app.app_context():
        with db.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
            with pytest.raises(Exception):
                connection.exec_driver_sql("INSERT INTO writing_version (id, writing_id, name, version_number, created_at, updated_at) VALUES ('bad','missing','invalid',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        db.session.remove()
        db.engine.dispose()


@pytest.mark.parametrize("volume,code", [
    (Volume("wrong", "NTFS", True, True), "WRONG_VOLUME"),
    (Volume(IDENTITY, "exFAT", True, True), "UNSUPPORTED_FILESYSTEM"),
    (Volume(IDENTITY, "NTFS", False, True), "UNSUPPORTED_FILESYSTEM"),
    (Volume(IDENTITY, "NTFS", True, False), "UNHEALTHY_VOLUME"),
])
def test_invalid_volume_never_creates_data_root(tmp_path, volume, code):
    root = tmp_path / "absent"
    with pytest.raises(StorageBlocked, match=code):
        initialize_storage(root, IDENTITY, lambda *_a, **_k: volume)
    assert not root.exists()


def test_missing_drive_never_creates_fallback(tmp_path):
    root = tmp_path / "not-mounted"
    def absent(*_a, **_k):
        raise StorageBlocked("VOLUME_UNAVAILABLE")
    with pytest.raises(StorageBlocked, match="VOLUME_UNAVAILABLE"):
        initialize_storage(root, IDENTITY, absent)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("root,identity,code", [("relative", IDENTITY, "INVALID_DATA_ROOT"), (None, None, "DATA_ROOT_REQUIRED")])
def test_startup_has_no_implicit_database(tmp_path, root, identity, code):
    with pytest.raises(StorageBlocked, match=code):
        create_app({"DATA_ROOT": root, "VOLUME_ID": identity})
    assert list(tmp_path.iterdir()) == []


def test_identity_must_be_explicit(tmp_path):
    with pytest.raises(StorageBlocked, match="VOLUME_ID_REQUIRED"):
        initialize_storage(tmp_path / "data", None, healthy)
    assert list(tmp_path.iterdir()) == []


def test_virtualized_data_root_is_rejected_before_initialization(tmp_path, monkeypatch):
    root = tmp_path / "approved"
    original = Path.resolve
    def redirected(path, *args, **kwargs):
        if path == root:
            return tmp_path / "unapproved-cache"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(StorageBlocked, match="DATA_ROOT_REDIRECTED"):
        initialize_storage(root, IDENTITY, healthy)
    assert list(tmp_path.iterdir()) == []


def test_existing_data_is_not_initialized_or_overwritten(tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    existing = root / "existing.sqlite3"
    existing.write_bytes(b"existing data must not be touched")
    before = hashlib.sha256(existing.read_bytes()).hexdigest()
    with pytest.raises(StorageBlocked, match="EXISTING_DATA_ROOT"):
        initialize_storage(root, IDENTITY, healthy)
    assert hashlib.sha256(existing.read_bytes()).hexdigest() == before
    assert list(root.iterdir()) == [existing]


def test_disconnect_latches_until_explicit_new_startup(tmp_path):
    root = tmp_path / "data"
    initialize_storage(root, IDENTITY, healthy)
    available = [True]
    def probe(*_a, **_k):
        if not available[0]:
            raise StorageBlocked("VOLUME_UNAVAILABLE")
        return healthy(None)
    guard = StorageGuard(root, IDENTITY, probe)
    guard.check(startup=True)
    available[0] = False
    with pytest.raises(StorageBlocked, match="VOLUME_UNAVAILABLE"):
        guard.check()
    available[0] = True
    with pytest.raises(StorageBlocked, match="VOLUME_UNAVAILABLE"):
        guard.check()
    StorageGuard(root, IDENTITY, probe).check(startup=True)


def test_missing_database_is_not_recreated(tmp_path):
    root = tmp_path / "data"
    paths = initialize_storage(root, IDENTITY, healthy)
    # Synthetic fixture only: simulate loss, preserving bytes under same root.
    paths["DATABASE_PATH"].rename(paths["DATABASE_PATH"].with_suffix(".fixture-disconnected"))
    with pytest.raises(StorageBlocked, match="DATABASE_MISSING"):
        StorageGuard(root, IDENTITY, healthy).check(startup=True)
    assert not paths["DATABASE_PATH"].exists()


def test_corrupt_database_and_unknown_migration_are_blocked(tmp_path):
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"not sqlite")
    with pytest.raises(StorageBlocked, match="DATABASE_STATE_UNVERIFIED"):
        check_database(bad)
    unknown = tmp_path / "unknown.db"
    with sqlite3.connect(unknown) as connection:
        connection.execute("CREATE TABLE valuable_data (body TEXT)")
        connection.execute("INSERT INTO valuable_data VALUES ('synthetic retained data')")
    with pytest.raises(StorageBlocked, match="DATABASE_STATE_UNVERIFIED"):
        check_database(unknown)
    with sqlite3.connect(unknown) as connection:
        assert connection.execute("SELECT body FROM valuable_data").fetchone()[0] == "synthetic retained data"


def test_repeated_alembic_upgrade_preserves_existing_rows(tmp_path):
    from flask import Flask
    from flask_migrate import upgrade
    from app.extensions import migrate
    root = tmp_path / "data"
    paths = initialize_storage(root, IDENTITY, healthy)
    with sqlite3.connect(paths["DATABASE_PATH"]) as connection:
        connection.execute("UPDATE workspace SET name='retained synthetic workspace'")
    app = Flask("migration-test")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + paths["DATABASE_PATH"].as_posix()
    db.init_app(app)
    directory = str(Path(__file__).resolve().parents[1] / "migrations")
    migrate.init_app(app, db, directory=directory)
    with app.app_context():
        upgrade(directory=directory)
        upgrade(directory=directory)
        assert db.session.execute(db.text("SELECT name FROM workspace")).scalar() == "retained synthetic workspace"
        db.session.remove()
        db.engine.dispose()
    check_database(paths["DATABASE_PATH"])


def test_online_backup_restores_into_isolated_sqlite(client, app, tmp_path):
    client.post("/api/writings", json={"title": "backup synthetic", "content": "가상 본문 🐧"})
    record = client.post("/api/backups", json={"includeUploads": False}).get_json()["data"]
    response = client.get(record["downloadUrl"])
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        snapshot = tmp_path / "snapshot.sqlite3"
        snapshot.write_bytes(archive.read("database/geulbit.db"))
    restored = tmp_path / "isolated-restore.sqlite3"
    source = sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(restored)
    try:
        source.backup(destination)
        assert destination.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert destination.execute("PRAGMA foreign_key_check").fetchall() == []
        assert destination.execute("SELECT content FROM writing").fetchone() == ("가상 본문 🐧",)
    finally:
        source.close()
        destination.close()
    assert list(Path(app.config["TEMP_FOLDER"]).iterdir()) == []


def test_production_api_fails_closed_and_storage_loss_is_503(tmp_path, monkeypatch):
    import app.storage as storage
    root = tmp_path / "data"
    initialize_storage(root, IDENTITY, healthy)
    actual_guard = StorageGuard
    monkeypatch.setattr(storage, "StorageGuard", lambda r, i: actual_guard(r, i, healthy))
    app = create_app({"DATA_ROOT": str(root), "VOLUME_ID": IDENTITY, "SECRET_STORE": MemorySecretStore()})
    client = app.test_client()
    readiness = client.get("/api/health")
    assert readiness.status_code == 503
    assert readiness.get_json()["data"]["database"] == "ok"
    assert readiness.get_json()["data"]["status"] == "blocked"
    assert client.get("/api/writings").status_code == 503
    assert client.post("/api/writings", json={"content": "must not be stored"}).status_code == 503
    guard = app.extensions["storage_guard"]
    guard.latch("VOLUME_UNAVAILABLE")
    assert client.get("/api/health").status_code == 503
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "linked"
    # Windows directory junction avoids developer-mode symlink permissions.
    import subprocess
    result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(root), str(outside)], capture_output=True)
    assert result.returncode == 0
    with pytest.raises(StorageBlocked, match="REPARSE_PATH_FORBIDDEN"):
        validate_volume(root, IDENTITY, healthy)
    assert list(outside.iterdir()) == []


def test_failed_initialization_is_not_automatically_retried(tmp_path, monkeypatch):
    from flask_migrate import upgrade
    def fail(*_a, **_k):
        raise RuntimeError("synthetic migration failure")
    monkeypatch.setattr("flask_migrate.upgrade", fail)
    root = tmp_path / "data"
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        initialize_storage(root, IDENTITY, healthy)
    assert (root / ".initializing").exists()
    with pytest.raises(StorageBlocked, match="EXISTING_DATA_ROOT"):
        initialize_storage(root, IDENTITY, healthy)
    with pytest.raises(StorageBlocked, match="EXPLICIT_INITIALIZATION_REQUIRED"):
        StorageGuard(root, IDENTITY, healthy).check(startup=True)


def test_insufficient_space_never_initializes(tmp_path, monkeypatch):
    from collections import namedtuple
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("app.storage.shutil.disk_usage", lambda _root: Usage(1024, 1024, 0))
    with pytest.raises(StorageBlocked, match="PARENT_OR_SPACE_UNAVAILABLE"):
        initialize_storage(tmp_path / "data", IDENTITY, healthy)
    assert list(tmp_path.iterdir()) == []


def test_40_concurrent_sqlite_writes_keep_integrity(tmp_path):
    root = tmp_path / "data"
    paths = initialize_storage(root, IDENTITY, healthy)
    with sqlite3.connect(paths["DATABASE_PATH"]) as connection:
        connection.execute("UPDATE workspace SET name='0'")
    def write(_index):
        connection = sqlite3.connect(paths["DATABASE_PATH"].as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                connection.execute("UPDATE workspace SET name=CAST(name AS INTEGER)+1")
        finally:
            connection.close()
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=40) as workers:
        list(workers.map(write, range(40)))
    elapsed = perf_counter() - started
    with sqlite3.connect(paths["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT name FROM workspace").fetchone() == ("40",)
    check_database(paths["DATABASE_PATH"])
    print(f"sqlite_synthetic_writes=40 workers=40 seconds={elapsed:.4f} lost_updates=0")
