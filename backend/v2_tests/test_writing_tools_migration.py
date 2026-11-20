import json
import pytest
from pathlib import Path
from sqlalchemy import text
from flask_migrate import upgrade,downgrade
from v2_fixture import v2app,user_client
from test_writing_tools_api import ROOT,data,draft,anchor
from app.extensions import db

MIGRATIONS=str(Path(__file__).parents[1]/'migrations')


def original_rows(connection):
    out={}
    for name, in connection.execute(text("select name from sqlite_master where type='table' and name not like 'sqlite_%' and name not in ('alembic_version','publication_requests')")):
        added={'annotation_kind','metadata_json'} if name=='user_annotations' else {'metadata_json','client_key','revision_number'} if name=='quote_card' else set()
        columns=[x[1] for x in connection.exec_driver_sql('pragma table_info("'+name+'")') if x[1] not in added]
        out[name]=connection.exec_driver_sql('select '+','.join('"'+x+'"' for x in columns)+' from "'+name+'" order by rowid').fetchall()
    return out


def test_actual_additive_forward_backward_preserves_legacy_columns(v2app):
    c,h,uid=user_client(v2app);w,v=draft(c,h)
    with v2app.app_context():
        db.session.remove()
        downgrade(directory=MIGRATIONS,revision='0004_user_annotations')
        with db.engine.begin() as conn:
            ws=conn.execute(text('select workspace_id from writing where id=:id'),{'id':w['id']}).scalar()
            stamp='2026-10-17 00:00:00'
            conn.execute(text('''INSERT INTO user_annotations(id,user_id,writing_id,essay_version_id,span_start,span_end,quote,content,revision_number,original_anchor,created_at,updated_at)
              VALUES('legacy-note',:u,:w,:v,0,8,:quote,'이전 개인 주석',1,:anchor,:at,:at)'''),{'u':uid,'w':w['id'],'v':v['id'],'quote':v['content'][:8],'anchor':json.dumps(anchor(v,0,8),ensure_ascii=False),'at':stamp})
            conn.execute(text('''INSERT INTO quote_card(id,workspace_id,owner_id,selected_text,quote_text,work,verification_status,created_at,updated_at)
              VALUES('legacy-card',:ws,:u,'이전 구절','이전 구절','기존 작품','확인 필요',:at,:at)'''),{'ws':ws,'u':uid,'at':stamp})
            before=original_rows(conn)
            assert 'annotation_kind' not in {x[1] for x in conn.exec_driver_sql('pragma table_info(user_annotations)')}
        upgrade(directory=MIGRATIONS,revision='0005_writing_tools')
        with db.engine.begin() as conn:
            assert original_rows(conn)==before
            assert conn.exec_driver_sql('pragma foreign_key_check').fetchall()==[]
            assert conn.exec_driver_sql('pragma integrity_check').scalar()=='ok'
        downgrade(directory=MIGRATIONS,revision='0004_user_annotations')
        with db.engine.begin() as conn:assert original_rows(conn)==before
        upgrade(directory=MIGRATIONS,revision='0005_writing_tools')
    assert data(c.get('/api/writings/'+w['id']))['content']==v['content']


def test_downgrade_refuses_to_destroy_new_private_metadata(v2app,monkeypatch):
    import flask_migrate
    errors=[];monkeypatch.setattr(flask_migrate.log,'error',errors.append)
    c,h,_=user_client(v2app);w,v=draft(c,h)
    row=data(c.post(ROOT+'/writings/'+w['id']+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':anchor(v,0,8)}),201)
    with v2app.app_context():
        db.session.remove()
        with pytest.raises(SystemExit) as rejected:
            downgrade(directory=MIGRATIONS,revision='0004_user_annotations')
        assert rejected.value.code==1 and errors[-1]=='Error: WRITING_TOOLS_DATA_REQUIRES_EXPLICIT_PRESERVATION'
        db.session.remove()
        assert db.session.execute(text('select version_num from alembic_version')).scalar()=='0005_writing_tools'
        assert db.session.execute(text('select quote from user_annotations where id=:id'),{'id':row['id']}).scalar()==row['quote']
    assert len(data(c.get(ROOT+'/writings/'+w['id']+'/marks')))==1


def test_unexpected_existing_column_type_is_not_silently_adopted(v2app,monkeypatch):
    import flask_migrate
    errors=[];monkeypatch.setattr(flask_migrate.log,'error',errors.append)
    with v2app.app_context():
        db.session.remove();downgrade(directory=MIGRATIONS,revision='0004_user_annotations')
        with db.engine.begin() as conn:conn.exec_driver_sql('ALTER TABLE user_annotations ADD COLUMN annotation_kind INTEGER')
        with pytest.raises(SystemExit) as rejected:
            upgrade(directory=MIGRATIONS,revision='0005_writing_tools')
        assert rejected.value.code==1 and errors[-1]=='Error: UNEXPECTED_WRITING_TOOLS_SCHEMA'
        db.session.remove()
        assert db.session.execute(text('select version_num from alembic_version')).scalar()=='0004_user_annotations'


def test_backup_revision_compatibility_keeps_exact_schema_validation(v2app):
    from app.storage import SCHEMA_HEAD
    from app.services.backup_service import SUPPORTED_REVISIONS,verify_db
    assert SCHEMA_HEAD=='0005_writing_tools'
    assert SUPPORTED_REVISIONS=={'0003_resource_ownership','0004_user_annotations','0005_writing_tools'}
    with v2app.app_context():
        raw=db.engine.raw_connection()
        try:verify_db(raw)
        finally:raw.close()
        db.session.remove();downgrade(directory=MIGRATIONS,revision='0004_user_annotations')
        raw=db.engine.raw_connection()
        try:
            verify_db(raw,'0004_user_annotations')
            with pytest.raises(ValueError,match='REVISION_UNSUPPORTED'):verify_db(raw)
            with pytest.raises(ValueError,match='REVISION_UNSUPPORTED'):verify_db(raw,'0002_geulbit_v2')
        finally:raw.close()
