"""Read/check initialized storage and verify a same-root SQLite backup/restore.

Never initialize, migrate, write synthetic rows, or restore over the live DB.
"""
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

from app import create_app
from app.extensions import db
from app.routes.data import _snapshot_database
from app.storage import StorageGuard, check_database


def signature(connection):
    # Compare all persistent state without logging rows or user content.
    import hashlib
    digest = hashlib.sha256()
    for statement in connection.iterdump():
        digest.update(statement.encode("utf-8"))
    return digest.hexdigest()


def main():
    root = os.environ["GEULBIT_DATA_ROOT"]
    identity = os.environ["GEULBIT_VOLUME_ID"]
    paths = StorageGuard(root, identity).check(startup=True)
    app = create_app({"DATA_ROOT": root, "VOLUME_ID": identity})
    with app.app_context():
        with db.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        target = Path(paths["BACKUP_FOLDER"]) / ("p01-verification-" + uuid.uuid4().hex + ".sqlite3")
        _snapshot_database(target)
        with closing(sqlite3.connect(paths["DATABASE_PATH"].as_uri() + "?mode=ro", uri=True)) as source:
            original = signature(source)
        with tempfile.TemporaryDirectory(prefix="p01-restore-", dir=paths["TEMP_FOLDER"]) as directory:
            restored = Path(directory) / "restored.sqlite3"
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(restored)) as destination:
                    source.backup(destination)
                    assert destination.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    assert destination.execute("PRAGMA foreign_key_check").fetchall() == []
                    assert signature(destination) == original
        db.session.remove()
        db.engine.dispose()
    # New app instance: verify storage survives a separate startup boundary.
    restarted = create_app({"DATA_ROOT": root, "VOLUME_ID": identity})
    with restarted.app_context():
        with db.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0001_initial"
        db.session.remove()
        db.engine.dispose()
    assert restarted.test_client().get("/api/writings").status_code == 503
    check_database(paths["DATABASE_PATH"])
    with closing(sqlite3.connect(paths["DATABASE_PATH"].as_uri() + "?mode=ro", uri=True)) as source:
        assert signature(source) == original
    print(json.dumps({"status": "PASS_LOCAL", "checks": 10, "fk": 1, "wal": True,
                      "busyTimeoutMs": 5000, "schema": "0001_initial", "integrity": "ok",
                      "restart": True, "backupRestore": True, "liveDatabaseUnchanged": True,
                      "userApiStatus": 503, "backup": str(target)}))


if __name__ == "__main__":
    main()
