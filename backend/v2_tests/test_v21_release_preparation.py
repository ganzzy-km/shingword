import base64,json,sqlite3,hashlib
from pathlib import Path
from datetime import datetime,timezone
import pytest
import v2_fixture
from flask import Flask
from flask_migrate import upgrade
from sqlalchemy import text
from app.extensions import db,migrate as migration_extension
from app.storage import Volume,StorageBlocked
from app.services.secrets_service import MemorySecretStore
from app.services import backup_service as backup
from app.services.storage_lease import StorageLease
from storage_cli import migrate_existing
import privacy_service

KEY=b'0123456789abcdef0123456789abcdef'
def healthy(*a,**k):return Volume('synthetic-volume-21','NTFS',True,True)

def old_root(tmp_path):
    root=tmp_path/'isolated-data';(root/'db').mkdir(parents=True);(root/'files').mkdir();(root/'temp').mkdir();(root/'operational/local-backups').mkdir(parents=True)
    path=root/'db/geulbit.sqlite3';app=Flask('old-schema-test');app.config['SQLALCHEMY_DATABASE_URI']='sqlite:///'+str(path)
    db.init_app(app);migration_extension.init_app(app,db,directory=str(Path(__file__).parents[1]/'migrations'))
    with app.app_context():
        upgrade(revision='0003_resource_ownership')
        db.session.execute(text('DROP TABLE user_annotations'));db.session.commit();db.session.remove();db.engine.dispose()
    with sqlite3.connect(path) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute("INSERT INTO app_settings(key,value,created_at,updated_at) VALUES('preserve-v21','{\"keep\":true}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    return root

def verified_archive(root):
    app=Flask('v21-backup-test');app.config.update(DATABASE_PATH=root/'db/geulbit.sqlite3',UPLOAD_FOLDER=root/'files',TEMP_FOLDER=root/'temp')
    with app.app_context():
        data=backup.build_bundle(KEY,quiescent=True,revision='0003_resource_ownership')
        backup.restore_bundle(data,KEY,root/'temp/restored-3',root/'db/geulbit.sqlite3',revision='0003_resource_ownership')
    archive=root/'operational/local-backups/geulbit-before.gbb';backup.write_bundle(archive,data)
    _,manifest=backup.read_bundle(data,KEY,revision='0003_resource_ownership')
    archive.with_suffix('.verified.json').write_text(json.dumps({'restoreVerified':True,'createdAt':manifest['createdAt'],'revision':manifest['revision'],'sha256':hashlib.sha256(data).hexdigest()}))
    return archive

def migrate(root,archive,confirmed=True):
    store=MemorySecretStore({'GEULBIT_BACKUP_ENCRYPTION_KEY':base64.b64encode(KEY).decode(),'synthetic-existing':'preserve'})
    result=migrate_existing(root,'synthetic-volume-21',archive,confirmed=confirmed,probe=healthy,store=store)
    assert store.get('synthetic-existing')=='preserve';return result

def test_explicit_verified_upgrade_and_legacy_receipt_not_due(tmp_path):
    root=old_root(tmp_path);archive=verified_archive(root)
    assert privacy_service.verified_last(archive.parent,KEY,datetime.now(timezone.utc)) is None
    with pytest.raises(ValueError,match='MANIFEST'):backup.read_bundle(archive.read_bytes(),KEY)
    result=migrate(root,archive);assert result['backupVerified'] and result['existingRowsPreserved'] and not result['serverStarted']
    with sqlite3.connect(root/'db/geulbit.sqlite3') as c:
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('0004_user_annotations',)
        assert c.execute("SELECT value FROM app_settings WHERE key='preserve-v21'").fetchone()==('{"keep":true}',)
        assert c.execute('PRAGMA integrity_check').fetchone()==('ok',) and c.execute('PRAGMA foreign_key_check').fetchall()==[]

def test_backup_changed_data_blocks_upgrade(tmp_path):
    root=old_root(tmp_path);archive=verified_archive(root)
    with sqlite3.connect(root/'db/geulbit.sqlite3') as c:c.execute("UPDATE app_settings SET value='false' WHERE key='preserve-v21'")
    with pytest.raises(StorageBlocked,match='BACKUP_NOT_CURRENT'):migrate(root,archive)
    with sqlite3.connect(root/'db/geulbit.sqlite3') as c:assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('0003_resource_ownership',)

def test_no_confirmation_or_live_writers_cannot_migrate(tmp_path):
    root=old_root(tmp_path);archive=verified_archive(root)
    with pytest.raises(StorageBlocked,match='CONFIRMATION'):migrate(root,archive,False)
    with StorageLease(root/'db/geulbit.sqlite3'):
        with pytest.raises(ValueError,match='ACTIVE'):migrate(root,archive)

def test_tampered_receipt_cannot_migrate(tmp_path):
    root=old_root(tmp_path);archive=verified_archive(root)
    receipt=json.loads(archive.with_suffix('.verified.json').read_text());receipt['sha256']='0'*64;archive.with_suffix('.verified.json').write_text(json.dumps(receipt))
    with pytest.raises(StorageBlocked,match='RECEIPT_INVALID'):migrate(root,archive)

def test_pre_migration_cli_always_creates_fresh_verified_legacy_backup(tmp_path,monkeypatch,capsys):
    from types import SimpleNamespace
    root=old_root(tmp_path);directory=root/'operational/local-backups'
    monkeypatch.setattr(privacy_service,'ROOT',root);monkeypatch.setattr(privacy_service,'assert_writers_stopped',lambda:None)
    store=MemorySecretStore({privacy_service.KEY:base64.b64encode(KEY).decode()})
    args=SimpleNamespace(command='backup',pre_migration_backup=True)
    privacy_service.maintenance(args,store,{'directory':str(directory)})
    privacy_service.maintenance(args,store,{'directory':str(directory)})
    assert len(list(directory.glob('*.gbb')))==len(list(directory.glob('*.verified.json')))==2
    assert 'NOT_DUE' not in capsys.readouterr().out
    assert privacy_service.verified_last(directory,KEY,datetime.now(timezone.utc)) is None


def test_real_secret_store_validation_accepts_legacy_only_explicitly(tmp_path,monkeypatch):
    import auth_setup
    from contextlib import nullcontext
    root=old_root(tmp_path);secret=root/'operational/secrets.dat'
    secret.write_bytes(b'synthetic-existing-encrypted-blob')
    monkeypatch.setattr(auth_setup,'ROOT',root)
    monkeypatch.setattr(auth_setup.winreg,'OpenKey',lambda *a:nullcontext(object()))
    monkeypatch.setattr(auth_setup.winreg,'QueryValueEx',lambda key,name:(str(root) if name=='GEULBIT_DATA_ROOT' else 'synthetic-volume-21',1))
    monkeypatch.setattr(auth_setup,'validate_volume',lambda path,volume:healthy())
    with pytest.raises(StorageBlocked,match='MIGRATION_REQUIRED'):auth_setup.approved_store()
    store=auth_setup.approved_store(before_v21_migration=True)
    assert store.path==secret and secret.read_bytes()==b'synthetic-existing-encrypted-blob'
    with sqlite3.connect(root/'db/geulbit.sqlite3') as c:c.execute("UPDATE alembic_version SET version_num='unknown_schema'")
    with pytest.raises(StorageBlocked,match='PRE_MIGRATION_REVISION'):auth_setup.approved_store(before_v21_migration=True)


def test_pre_migration_cli_requests_explicit_legacy_secret_access(tmp_path,monkeypatch,capsys):
    import sys
    root=old_root(tmp_path);calls=[]
    monkeypatch.setattr(privacy_service,'ROOT',root)
    monkeypatch.setattr(privacy_service,'config',lambda:{'directory':str(root/'operational/local-backups')})
    monkeypatch.setattr(privacy_service,'assert_writers_stopped',lambda:None)
    store=MemorySecretStore({privacy_service.KEY:base64.b64encode(KEY).decode()})
    monkeypatch.setattr(privacy_service,'approved_store',lambda **kwargs:(calls.append(kwargs) or store))
    monkeypatch.setattr(sys,'argv',['privacy_service.py','backup','--pre-migration-backup'])
    privacy_service.main()
    assert calls==[{'before_v21_migration':True}]
    assert len(list((root/'operational/local-backups').glob('*.verified.json')))==1
    assert base64.b64encode(KEY).decode() not in capsys.readouterr().out
