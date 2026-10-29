"""Explicit storage initialization/check, separate from HTTP server startup."""
import argparse
import json
import os
from app.storage import SCHEMA_HEAD, StorageBlocked, StorageGuard, initialize_storage

def migrate_existing(root,identity,archive,*,confirmed=False,probe=None,store=None):
    """Explicit single additive upgrade, only behind a fresh verified 0003 backup."""
    if not confirmed:raise StorageBlocked('EXPLICIT_MIGRATION_CONFIRMATION_REQUIRED')
    if SCHEMA_HEAD!='0004_user_annotations':raise StorageBlocked('V21_MIGRATION_TARGET_REQUIRED')
    import base64,hashlib,sqlite3
    from pathlib import Path
    from contextlib import closing
    from datetime import datetime,timezone,timedelta
    from app.storage import validate_volume,windows_volume,db_path,check_database
    from app.services.storage_lease import StorageLease
    from app.services.backup_service import read_bundle,LIMIT
    from auth_setup import approved_store
    from flask import Flask
    from flask_migrate import upgrade
    from app.extensions import db,migrate
    original_root=Path(root).absolute();root=original_root.resolve()
    if original_root!=root:raise StorageBlocked('DATA_ROOT_REDIRECTED')
    if not archive:raise StorageBlocked('APPROVED_VERIFIED_BACKUP_REQUIRED')
    validate_volume(root,identity,probe or windows_volume)
    database=db_path(root)
    if not database.is_file() or database.is_symlink():raise StorageBlocked('DATABASE_MISSING')
    original_archive=Path(archive).absolute()
    if original_archive.is_symlink():raise StorageBlocked('APPROVED_VERIFIED_BACKUP_REQUIRED')
    archive=original_archive.resolve()
    if (archive.parent!=(root/'operational/local-backups').resolve() or archive.is_symlink()
        or not archive.is_file() or archive.stat().st_size>LIMIT+1024*1024):raise StorageBlocked('APPROVED_VERIFIED_BACKUP_REQUIRED')
    proof=archive.with_suffix('.verified.json')
    if proof.is_symlink() or not proof.is_file() or proof.stat().st_size>4096:raise StorageBlocked('VERIFIED_BACKUP_RECEIPT_REQUIRED')
    with StorageLease(database,exclusive=True):
        raw=archive.read_bytes();receipt=json.loads(proof.read_text(encoding='utf-8'))
        if receipt.get('restoreVerified') is not True or receipt.get('sha256')!=hashlib.sha256(raw).hexdigest():raise StorageBlocked('BACKUP_RECEIPT_INVALID')
        key=base64.b64decode((store or approved_store(before_v21_migration=True)).get('GEULBIT_BACKUP_ENCRYPTION_KEY'),validate=True)
        members,manifest=read_bundle(raw,key,revision='0003_resource_ownership')
        created=datetime.fromisoformat(manifest['createdAt']);now=datetime.now(timezone.utc)
        if (now-created>timedelta(minutes=10) or receipt.get('createdAt')!=manifest['createdAt']
            or receipt.get('revision')!='0003_resource_ownership'
            or manifest['sourceIdentity']!=hashlib.sha256(str(database.resolve()).encode()).hexdigest()):raise StorageBlocked('FRESH_EXACT_BACKUP_REQUIRED')
        def inventory(connection):
            names=[r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {n:connection.execute('SELECT * FROM "'+n+'" ORDER BY rowid').fetchall() for n in names}
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as live,closing(sqlite3.connect(':memory:')) as image:
            if (live.execute('SELECT version_num FROM alembic_version').fetchone()!=('0003_resource_ownership',)
                or live.execute('PRAGMA integrity_check').fetchone()!=('ok',) or live.execute('PRAGMA foreign_key_check').fetchall()
                or live.execute('PRAGMA journal_mode').fetchone()!=('wal',)):raise StorageBlocked('EXPECTED_SCHEMA_STATE_REQUIRED')
            payload=bytearray(members['database.sqlite3']);payload[18:20]=b'\x01\x01';image.deserialize(bytes(payload))
            before=inventory(live)
            if inventory(image)!=before:raise StorageBlocked('BACKUP_NOT_CURRENT')
        for name,content in members.items():
            if not name.startswith('files/'):continue
            path=root/name
            if path.is_symlink() or not path.resolve().is_relative_to(root/'files') or path.read_bytes()!=content:raise StorageBlocked('BACKUP_FILES_NOT_CURRENT')
        app=Flask('explicit-v21-migration');app.config['SQLALCHEMY_DATABASE_URI']='sqlite:///file:'+database.as_posix()+'?mode=rw&uri=true'
        db.init_app(app);migrate.init_app(app,db,directory=str(Path(__file__).parent/'migrations'))
        with app.app_context():
            upgrade(revision='0004_user_annotations');db.session.remove();db.engine.dispose()
        check_database(database,writable=True)
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as after:
            rows=inventory(after)
            if any(rows[n]!=value for n,value in before.items() if n!='alembic_version'):raise StorageBlocked('MIGRATION_DATA_PRESERVATION_FAILED')
        return {'status':'PASS','operation':'migrate','schema':SCHEMA_HEAD,'existingRowsPreserved':True,'backupVerified':True,'serverStarted':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "check", "migrate"])
    parser.add_argument('--verified-backup');parser.add_argument('--confirm-v21',action='store_true')
    args = parser.parse_args()
    root, identity = os.getenv("GEULBIT_DATA_ROOT"), os.getenv("GEULBIT_VOLUME_ID")
    if not root:
        raise StorageBlocked("DATA_ROOT_REQUIRED")
    if args.command == 'migrate':
        print(json.dumps(migrate_existing(root,identity,args.verified_backup,confirmed=args.confirm_v21)));return
    if args.command == "init":
        initialize_storage(root, identity)
    else:
        StorageGuard(root, identity).check(startup=True)
    print(json.dumps({"status": "PASS", "operation": args.command, "schema": SCHEMA_HEAD}))


if __name__ == "__main__":
    try:
        main()
    except StorageBlocked as error:
        print(json.dumps({"status": "BLOCKED", "code": error.code}))
        raise SystemExit(1)
    except Exception as error:
        print(json.dumps({'status':'BLOCKED','code':'STORAGE_OPERATION_FAILED','errorType':type(error).__name__}))
        raise SystemExit(1)
