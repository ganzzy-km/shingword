import sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from v2_fixture import v2app,user_client
from test_analysis_api import essay
from app.extensions import db
from app.services import backup_service as backup

KEY=b'0123456789abcdef0123456789abcdef'


def test_encrypted_restore_reapplies_delete_and_invalidates_sessions(v2app,tmp_path):
    c,h,uid=user_client(v2app);w=essay(c,h,'synthetic private body')
    with v2app.app_context():
        data=backup.build_bundle(KEY,quiescent=True)
        assert b'synthetic private body' not in data and b'PK\x03\x04' not in data
    assert c.delete('/api/writings/'+w['id'],headers=h,json={'confirmation':w['title']}).status_code==200
    with v2app.app_context():
        result=backup.restore_bundle(data,KEY,tmp_path/'restore',v2app.config['DATABASE_PATH'])
    assert result['quarantined'] and result['sessionsInvalidated']
    with sqlite3.connect(tmp_path/'restore/db/geulbit.sqlite3') as restored:
        assert restored.execute('SELECT count(*) FROM writing').fetchone()[0]==0
        assert restored.execute('SELECT session_version FROM users WHERE id=?',(uid,)).fetchone()[0]>0
        assert restored.execute("SELECT value FROM app_settings WHERE key='restore_quarantine'").fetchone()[0]=='true'


def test_wrong_key_corruption_expiry_and_future_rejected(v2app,tmp_path):
    with v2app.app_context():data=backup.build_bundle(KEY,quiescent=True)
    for damaged,key in [(data[:-1]+bytes([data[-1]^1]),KEY),(data,b'x'*32)]:
        with pytest.raises(ValueError,match='AUTHENTICATION'):backup.read_bundle(damaged,key)
    now=datetime.now(timezone.utc)
    with v2app.app_context():old=backup.build_bundle(KEY,quiescent=True,now=now-timedelta(days=7))
    with pytest.raises(ValueError,match='EXPIRED'):backup.read_bundle(old,KEY,now)
    with pytest.raises(ValueError,match='WRITERS'):
        with v2app.app_context():backup.build_bundle(KEY)
    with pytest.raises(sqlite3.OperationalError):backup.restore_bundle(data,KEY,tmp_path/'never-created',tmp_path/'missing-authority')
    assert not (tmp_path/'never-created').exists()


def test_exclusive_write_space_failure_and_daily_schedule(tmp_path,monkeypatch):
    target=tmp_path/'encrypted.gbb';target.write_bytes(b'preserve')
    with pytest.raises(ValueError,match='PRESERVED'):backup.write_bundle(target,b'x')
    assert target.read_bytes()==b'preserve'
    import collections
    Usage=collections.namedtuple('Usage','total used free')
    monkeypatch.setattr(backup.shutil,'disk_usage',lambda _:Usage(1,1,0))
    with pytest.raises(ValueError,match='SPACE'):backup.write_bundle(tmp_path/'no-space.gbb',b'x')
    now=datetime.now(timezone.utc)
    assert backup.backup_due(None,now) and backup.backup_due(now-timedelta(days=1),now)
    assert not backup.backup_due(now-timedelta(hours=23),now)


def test_no_device_guess_or_same_disk(v2app,monkeypatch,tmp_path):
    monkeypatch.setattr(backup,'validate_volume',lambda *a:None)
    monkeypatch.setattr(backup,'physical_disk',lambda _: 'synthetic-same-disk')
    with pytest.raises(ValueError,match='SEPARATE'):backup.validate_device(tmp_path,tmp_path,'synthetic-volume','synthetic-same-disk')


def test_withdraw_restore_does_not_resurrect_file(v2app,tmp_path):
    import io
    from app.models import SourceDocument
    c,h,uid=user_client(v2app);essay(c,h)
    doc=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(b'synthetic secret'),'source.txt')}).json['data']
    with v2app.app_context():
        filename=db.session.get(SourceDocument,doc['id']).stored_name
        data=backup.build_bundle(KEY,quiescent=True)
    assert c.post('/api/account/withdraw',headers=h,json={'confirmation':'WITHDRAW'}).status_code==200
    with v2app.app_context():backup.restore_bundle(data,KEY,tmp_path/'withdraw-restore',v2app.config['DATABASE_PATH'])
    with sqlite3.connect(tmp_path/'withdraw-restore/db/geulbit.sqlite3') as c:
        assert c.execute('SELECT count(*) FROM writing').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM source_document').fetchone()[0]==0
        assert c.execute('SELECT status FROM users WHERE id=?',(uid,)).fetchone()[0]=='INACTIVE'
    assert not (tmp_path/'withdraw-restore/files'/filename).exists()


def test_authenticated_traversal_and_manifest_mismatch_rejected():
    import io,json,os,zipfile
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    for name,hashvalue in [('../outside','x'),('database.sqlite3','incorrect-sha')]:
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            archive.writestr(name,b'synthetic')
            archive.writestr('manifest.json',json.dumps({'format':1,'revision':backup.REVISION,'createdAt':datetime.now(timezone.utc).isoformat(),'sha256':{name:hashvalue}}))
        nonce=os.urandom(12);data=backup.MAGIC+nonce+AESGCM(KEY).encrypt(nonce,stream.getvalue(),backup.MAGIC)
        with pytest.raises(ValueError,match='UNSAFE|HASH'):backup.read_bundle(data,KEY)


def test_interrupted_write_has_no_success_or_truncated_backup(tmp_path,monkeypatch):
    import os
    monkeypatch.setattr(os,'fsync',lambda _:(_ for _ in ()).throw(OSError('synthetic interruption')))
    target=tmp_path/'incomplete.gbb'
    with pytest.raises(OSError):backup.write_bundle(target,b'encrypted-test')
    assert not target.exists()


def test_only_verified_encrypted_expired_backups_pruned(v2app,tmp_path):
    now=datetime.now(timezone.utc)
    with v2app.app_context():
        old=backup.build_bundle(KEY,quiescent=True,now=now-timedelta(days=7))
        fresh=backup.build_bundle(KEY,quiescent=True,now=now-timedelta(days=6))
    (tmp_path/'geulbit-old.gbb').write_bytes(old);(tmp_path/'geulbit-fresh.gbb').write_bytes(fresh)
    (tmp_path/'user-file.txt').write_text('preserve')
    assert backup.prune_encrypted(tmp_path,KEY,now)==1
    assert (tmp_path/'geulbit-fresh.gbb').exists() and (tmp_path/'user-file.txt').exists()


def test_old_archive_cannot_restore_erased_google_identity(v2app,tmp_path):
    from app.models import User
    _,_,uid=user_client(v2app)
    with v2app.app_context():
        data=backup.build_bundle(KEY,quiescent=True)
        user=db.session.get(User,uid);user.oidc_issuer='urn:geulbit:erased-owner';user.oidc_subject='synthetic-erased';user.email=None;user.status='INACTIVE';db.session.commit()
        with pytest.raises(ValueError,match='ERASED_IDENTITY'):
            backup.restore_bundle(data,KEY,tmp_path/'never-written',v2app.config['DATABASE_PATH'])
    assert not (tmp_path/'never-written').exists()


def test_restore_discards_expired_independent_private_document(v2app,tmp_path):
    import io
    c,h,_=user_client(v2app);r=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(b'synthetic old file'),'old.txt')});assert r.status_code==201
    future=datetime.now(timezone.utc)+timedelta(days=8)
    with v2app.app_context():
        data=backup.build_bundle(KEY,quiescent=True,now=future)
        result=backup.restore_bundle(data,KEY,tmp_path/'expired-document-restore',v2app.config['DATABASE_PATH'],now=future)
        assert result['files']==0
    with sqlite3.connect(tmp_path/'expired-document-restore/db/geulbit.sqlite3') as c:assert c.execute('SELECT count(*) FROM source_document').fetchone()[0]==0
