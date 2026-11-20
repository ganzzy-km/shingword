import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]))
import staging_service as staging


def paths_for(root, operating):
    return staging.profile_paths('STAGING', root, expected_root=root, operating_root=operating)


@pytest.mark.parametrize('profile,root',[(None,None),('',None),('OPERATING','unused'),('staging','unused')])
def test_explicit_profile_and_root_required_before_writes(tmp_path,profile,root):
    with pytest.raises(ValueError,match='EXPLICIT_STAGING'):
        staging.profile_paths(profile,root)
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('kind',['same','child','parent','external','external-child'])
def test_operating_and_external_overlap_rejected_without_opening_db(tmp_path,kind):
    operating=tmp_path/'mock-operating'
    roots={'same':operating,'child':operating/'temp/staging','parent':tmp_path,
           'external':staging.EXTERNAL_ROOT,'external-child':staging.EXTERNAL_ROOT/'test'}
    with pytest.raises(ValueError,match='OPERATING_PATH_FORBIDDEN'):
        paths_for(roots[kind],operating)
    assert not operating.exists()


def test_unknown_relative_or_dotdot_path_never_creates_fallback(tmp_path):
    with pytest.raises(ValueError,match='ABSOLUTE_ROOT'):
        staging.profile_paths('STAGING','relative')
    with pytest.raises(ValueError,match='ABSOLUTE_ROOT'):
        paths_for(tmp_path/'unknown/../staging',tmp_path/'operating')
    with pytest.raises(ValueError,match='EXACT_STAGING_ROOT'):
        staging.profile_paths('STAGING',tmp_path/'unknown')
    assert list(tmp_path.iterdir())==[]


def test_windows_case_normalization_same_approved_root(tmp_path):
    root=tmp_path/'Staging'
    result=staging.profile_paths('STAGING',str(root).upper(),expected_root=root,operating_root=tmp_path/'operating')
    assert staging.norm(result['root'])==staging.norm(root)
    assert not root.exists()


def test_database_hardlink_to_mock_operating_rejected(tmp_path):
    source=tmp_path/'mock-operating';source.mkdir()
    original=source/'geulbit.sqlite3';original.write_bytes(b'synthetic mock database')
    root=tmp_path/'staging';(root/'db').mkdir(parents=True)
    os.link(original,root/'db/geulbit.sqlite3')
    with pytest.raises(ValueError,match='HARDLINK_FORBIDDEN'):
        paths_for(root,source)
    assert original.read_bytes()==b'synthetic mock database'


def test_junction_root_rejected_before_any_database_access(tmp_path):
    target=tmp_path/'mock-operating';target.mkdir()
    sentinel=target/'untouched.txt';sentinel.write_text('synthetic protected bytes')
    root=tmp_path/'staging'
    command="New-Item -ItemType Junction -Path '"+str(root).replace("'","''")+"' -Target '"+str(target).replace("'","''")+"' | Out-Null"
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],check=True,capture_output=True)
    with pytest.raises(ValueError,match='REPARSE'):
        paths_for(root,target)
    assert sentinel.read_text()=='synthetic protected bytes'


def test_nested_junction_rejected_without_following_it(tmp_path):
    target=tmp_path/'mock-operating';target.mkdir()
    root=tmp_path/'staging';root.mkdir()
    command="New-Item -ItemType Junction -Path '"+str(root/'files').replace("'","''")+"' -Target '"+str(target).replace("'","''")+"' | Out-Null"
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],check=True,capture_output=True)
    with pytest.raises(ValueError,match='REPARSE'):
        paths_for(root,target)
    assert list(target.iterdir())==[]


def test_existing_unowned_directory_preserved(tmp_path):
    root=tmp_path/'staging';root.mkdir();keep=root/'unknown.bin';keep.write_bytes(b'do not reset')
    paths=paths_for(root,tmp_path/'operating')
    with pytest.raises(ValueError,match='OWNERSHIP_MARKER_REQUIRED'):
        staging.initialize(paths)
    assert keep.read_bytes()==b'do not reset' and list(root.iterdir())==[keep]


@pytest.fixture
def initialized(tmp_path):
    paths=paths_for(tmp_path/'staging',tmp_path/'mock-operating')
    assert staging.initialize(paths)['status']=='STAGING_INITIALIZED'
    return paths


def test_init_uses_0004_and_preserves_existing_synthetic_records(initialized):
    p=initialized
    with closing(sqlite3.connect(p['database'].as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()==('0004_user_annotations',)
        assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        original=db.execute('SELECT id,oidc_issuer,oidc_subject FROM users ORDER BY id').fetchall()
        assert len(original)==2 and all(row[1]=='urn:geulbit:staging' for row in original)
    secret=p['secrets'].read_bytes()
    assert staging.initialize(p)['status']=='EXISTING_STAGING_PRESERVED'
    assert p['secrets'].read_bytes()==secret
    with closing(sqlite3.connect(p['database'].as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('SELECT id,oidc_issuer,oidc_subject FROM users ORDER BY id').fetchall()==original


def test_missing_db_does_not_initialize_implicitly(initialized):
    p=initialized;p['database'].rename(p['database'].with_suffix('.preserved'))
    with pytest.raises(Exception,match='DATABASE_MISSING'):
        staging.owned_profile(p)
    assert not p['database'].exists()


def test_incorrect_schema_is_not_upgraded_or_reset(initialized):
    with closing(sqlite3.connect(initialized['database'])) as db:
        db.execute("UPDATE alembic_version SET version_num='unapproved-schema'");db.commit()
    with pytest.raises(Exception,match='MIGRATION_REQUIRED'):
        staging.owned_profile(initialized)
    with closing(sqlite3.connect(initialized['database'].as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='unapproved-schema'


def test_all_write_namespaces_and_environment_are_staging_only(initialized,monkeypatch):
    monkeypatch.setenv('GEULBIT_DATA_ROOT','synthetic-unrelated-operating-default')
    monkeypatch.setenv('GEULBIT_SESSION_SIGNING_KEY','synthetic-global-key-must-not-be-used')
    app=staging.create_staging_app(initialized)
    try:
        assert not app.testing
        for key in ['DATABASE_PATH','UPLOAD_FOLDER','TEMP_FOLDER','BACKUP_FOLDER','SECRET_FILE','ADMIN_STATE_FILE','ADMIN_AUDIT_FILE']:
            assert Path(app.config[key]).resolve().is_relative_to(initialized['root'].resolve())
        assert app.config['SESSION_SIGNING_KEY']!='synthetic-global-key-must-not-be-used'
        assert app.config['DATA_ROOT']==str(initialized['root'])
        assert app.config['GEULBIT_S4_ENGINE'] is True and app.config['GEULBIT_V22'] is False
        assert app.config['RETENTION_APPROVED'] is False and app.config['AI_PROVIDER'] is None
        assert app.config.get('OIDC_FLOW') is None
        assert os.environ['TEMP']==str(initialized['temp'])
        assert os.environ['XDG_CACHE_HOME']==str(initialized['cache'])
    finally:staging.close_app(app)


def test_cookie_namespace_existing_auth_csrf_and_ownership(initialized):
    app=staging.create_staging_app(initialized)
    try:
        c=app.test_client();base='https://localhost:'+str(staging.PORT)
        r=c.get('/__staging__/session/student-a',base_url=base)
        assert r.status_code==302
        assert r.headers['Set-Cookie'].startswith(staging.COOKIE+'=')
        assert all(v in r.headers['Set-Cookie'] for v in ['Secure','HttpOnly','SameSite=Lax'])
        token=c.get_cookie(staging.COOKIE,domain='localhost').value
        session=c.get('/api/auth/session',base_url=base)
        assert session.status_code==200
        h={'X-CSRF-Token':session.json['data']['csrfToken']}
        assert c.post('/api/writings',base_url=base,json={'content':'synthetic'},headers={}).status_code==401
        created=c.post('/api/writings',base_url=base,json={'title':'staging only','content':'가상 글 😀'},headers=h)
        assert created.status_code==201
        other=app.test_client();other.get('/__staging__/session/student-b',base_url=base)
        assert other.get('/api/writings/'+created.json['data']['id'],base_url=base).status_code==404
        ordinary=app.test_client();ordinary.set_cookie('geulbit_session',token,domain='localhost')
        assert ordinary.get('/api/auth/session',base_url=base).status_code==401
        # Existing SPA fallback may return index.html for an unknown non-API URL.
        assert '/__qa__/session/<name>' not in {str(rule) for rule in app.url_map.iter_rules()}
        fallback=c.get('/__qa__/session/admin',base_url=base)
        assert fallback.headers.get('Set-Cookie') is None
        assert c.get('/api/auth/session',base_url=base).json['data']['id']==session.json['data']['id']
    finally:staging.close_app(app)


def test_two_apps_do_not_accept_each_others_signing_material(initialized,tmp_path):
    from app.v2.auth_api import boundary
    from app.v2.common import principal
    from app.models import User
    from components.auth import AuthDenied
    second=paths_for(tmp_path/'second-staging',tmp_path/'mock-operating')
    staging.initialize(second)
    a=staging.create_staging_app(initialized);b=staging.create_staging_app(second)
    try:
        assert a.config['SESSION_SIGNING_KEY']!=b.config['SESSION_SIGNING_KEY']
        with b.app_context():user=principal(User.query.filter_by(oidc_subject=staging.SUBJECTS['student-a']).one())
        with a.app_context():foreign,_=boundary().issue(user)
        with b.app_context():
            with pytest.raises(AuthDenied,match='ACCESS_DENIED'):
                boundary().verify(foreign,load_user=lambda _uid:user)
        c=b.test_client();c.set_cookie(staging.COOKIE,foreign,domain='localhost')
        assert c.get('/api/auth/session',base_url='https://localhost:'+str(staging.PORT)).status_code==401
    finally:staging.close_app(a);staging.close_app(b)


@pytest.mark.parametrize('remote,host,scheme',[('198.51.100.7','localhost:8786','https'),('127.0.0.1','outside.invalid','https'),('127.0.0.1','localhost:8786','http')])
def test_qa_session_boundary_rejects_nonloopback_or_wrong_origin(remote,host,scheme):
    calls=[]
    adapter=staging.StagingBoundary(lambda *_:calls.append(True),'localhost:8786')
    statuses=[]
    result=adapter({'REMOTE_ADDR':remote,'HTTP_HOST':host,'wsgi.url_scheme':scheme},lambda status,_headers:statuses.append(status))
    assert statuses==['400 Bad Request'] and not calls
    assert b'STAGING_LOOPBACK_ORIGIN_REQUIRED' in b''.join(result)


def test_port_conflict_does_not_stop_or_replace_another_listener(monkeypatch):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen()
        monkeypatch.setattr(staging,'PORT',listener.getsockname()[1])
        with pytest.raises(ValueError,match='PORT_OCCUPIED_NO_PROCESS_STOPPED'):
            staging.available_port()
        assert listener.fileno()!=-1


def test_stop_refuses_an_operating_style_event_identity(initialized,monkeypatch):
    state={'profile':'STAGING','script':str(staging.SCRIPT),'root':str(initialized['root']),
           'process':{'pid':1},'stopId':'operating-style-id'}
    staging.write(initialized['state'],state)
    with pytest.raises(ValueError,match='PROCESS_OWNERSHIP_MISMATCH'):
        staging.signal_stop(initialized)


def test_entrypoint_does_not_import_or_dispatch_operator_maintenance():
    import ast
    tree=ast.parse(staging.SCRIPT.read_text(encoding='utf-8'))
    calls={n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,(ast.Name,ast.Attribute))}
    assert not calls & {'approved_store','maintenance_cycle','scheduler_install','sync_once','restore_bundle','purge_due_essays'}
