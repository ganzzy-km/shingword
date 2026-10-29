import json
from pathlib import Path
import pytest
import v2_fixture  # Reuse the existing backend import-path setup.
from v2_fixture import v2app
import privacy_service as cli
from app.services.secrets_service import MemorySecretStore


def test_key_registration_preserves_existing_keys_and_never_prints_key(monkeypatch,capsys):
    import sys
    store=MemorySecretStore();store.set('synthetic-existing','preserve')
    monkeypatch.setattr(cli,'approved_store',lambda:store)
    monkeypatch.setattr(sys,'argv',['privacy_service.py','backup-key'])
    cli.main();first=store.get(cli.KEY)
    cli.main();output=capsys.readouterr().out
    assert first==store.get(cli.KEY) and store.get('synthetic-existing')=='preserve'
    assert first not in output and 'REGISTERED_DPAPI' in output


def test_writer_presence_and_missing_device_fail_closed(monkeypatch,tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(cli.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout='1'))
    with pytest.raises(ValueError,match='WRITERS'):cli.assert_writers_stopped()
    monkeypatch.setattr(cli,'CONFIG',tmp_path/'not-configured.json')
    with pytest.raises(ValueError,match='NOT_CONFIGURED'):cli.config()


def test_verified_scratch_cleanup_cannot_delete_unrelated_root(monkeypatch,tmp_path):
    monkeypatch.setattr(cli,'ROOT',tmp_path/'synthetic-data')
    target=cli.ROOT/'temp/restore-check-synthetic'
    for name in ['db','files']:
        (target/name).mkdir(parents=True);(target/name/'synthetic').write_text('synthetic')
    cli.discard_verified_isolation(target);assert not target.exists()
    outside=tmp_path/'outside';outside.mkdir()
    with pytest.raises(ValueError,match='BLOCKED'):cli.discard_verified_isolation(outside)
    assert outside.exists()


def test_approved_local_backup_mode_stays_in_pinned_root(monkeypatch,tmp_path):
    from app import storage
    root=tmp_path/'data';target=root/'operational/local-backups';target.mkdir(parents=True)
    monkeypatch.setattr(cli,'ROOT',root);monkeypatch.setattr(cli,'CONFIG',root/'operational/backup-config.json')
    seen=[];monkeypatch.setattr(storage,'validate_volume',lambda path,identity:seen.append((path,identity)))
    value={'approved':True,'mode':'local-c-7d-v1','directory':str(target),'volumeId':'synthetic-volume','retentionDays':7,'frequencyHours':24}
    cli.CONFIG.write_text(json.dumps(value));assert cli.config()==value
    assert seen==[(root,'synthetic-volume'),(target,'synthetic-volume')]
    value['directory']=str(tmp_path/'outside');cli.CONFIG.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='INVALID'):cli.config()


def test_unverified_archive_cannot_postpone_backup(tmp_path,monkeypatch):
    from datetime import datetime,timezone
    target=tmp_path/'geulbit-unverified.gbb';target.write_bytes(b'synthetic-previous-failed-restore')
    now=datetime.now(timezone.utc)
    assert cli.verified_last(tmp_path,b'x'*32,now) is None
    target.with_suffix('.verified.json').write_text(json.dumps({'restoreVerified':True,'sha256':'wrong'}))
    with pytest.raises(ValueError,match='RECEIPT'):cli.verified_last(tmp_path,b'x'*32,now)


def test_storage_lease_blocks_server_backup_start_race(tmp_path):
    from app.services.storage_lease import StorageLease
    database=tmp_path/'db/example.sqlite3';database.parent.mkdir()
    with StorageLease(database):
        with StorageLease(database):pass
        with pytest.raises(ValueError,match='ACTIVE'):StorageLease(database,exclusive=True)
    with StorageLease(database,exclusive=True):
        with pytest.raises(ValueError,match='ACTIVE'):StorageLease(database)
        with pytest.raises(ValueError,match='ACTIVE'):StorageLease(database,exclusive=True)
    with StorageLease(database):pass


def test_restore_failure_archive_cannot_issue_not_due_on_retry(v2app,tmp_path,monkeypatch,capsys):
    import base64,sqlite3
    from types import SimpleNamespace
    from datetime import datetime,timezone
    from app.services.secrets_service import MemorySecretStore
    root=tmp_path/'root';(root/'db').mkdir(parents=True);(root/'files').mkdir();(root/'temp').mkdir();directory=root/'backups';directory.mkdir()
    with sqlite3.connect(v2app.config['DATABASE_PATH']) as source,sqlite3.connect(root/'db/geulbit.sqlite3') as target:source.backup(target)
    monkeypatch.setattr(cli,'ROOT',root);monkeypatch.setattr(cli,'assert_writers_stopped',lambda:None)
    key=b'0123456789abcdef0123456789abcdef';store=MemorySecretStore();store.set(cli.KEY,base64.b64encode(key).decode())
    args=SimpleNamespace(command='backup');cfg={'directory':str(directory)};real_restore=cli.restore_bundle
    monkeypatch.setattr(cli,'restore_bundle',lambda *a,**kw:(_ for _ in ()).throw(ValueError('synthetic restore interruption')))
    with pytest.raises(ValueError,match='interruption'):cli.maintenance(args,store,cfg)
    assert len(list(directory.glob('*.gbb')))==1 and not list(directory.glob('*.verified.json'))
    assert cli.verified_last(directory,key,datetime.now(timezone.utc)) is None
    monkeypatch.setattr(cli,'restore_bundle',real_restore);cli.maintenance(args,store,cfg)
    assert len(list(directory.glob('*.gbb')))==2 and len(list(directory.glob('*.verified.json')))==1
    assert cli.verified_last(directory,key,datetime.now(timezone.utc)) is not None
    cli.maintenance(args,store,cfg);assert 'NOT_DUE' in capsys.readouterr().out


def test_storage_lease_cross_process_and_crash_release(tmp_path):
    import subprocess,sys,os
    from app.services.storage_lease import StorageLease
    database=tmp_path/'db/example.sqlite3';database.parent.mkdir()
    code="from app.services.storage_lease import StorageLease; import sys; lease=StorageLease(sys.argv[1],exclusive=True); print('LOCKED',flush=True); sys.stdin.readline()"
    # A Windows venv executable may be a launcher. Terminate the actual worker,
    # otherwise its still-open stdin keeps the OS lease alive after launcher exit.
    worker=getattr(sys,'_base_executable',sys.executable) if os.name=='nt' else sys.executable
    environment=dict(os.environ);environment['PYTHONPATH']=str(Path(sys.prefix)/'Lib/site-packages')+os.pathsep+str(Path(__file__).parents[1])
    process=subprocess.Popen([worker,'-c',code,str(database)],env=environment,cwd=str(Path(__file__).parents[1]),stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert process.stdout.readline().strip()=='LOCKED'
        with pytest.raises(ValueError,match='ACTIVE'):StorageLease(database)
    finally:process.terminate();process.wait(timeout=10);process.stdin.close();process.stdout.close()
    with StorageLease(database):pass
