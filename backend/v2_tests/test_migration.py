import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from flask import Flask
from flask_migrate import upgrade, downgrade
from sqlalchemy import event, text

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.extensions import db, migrate
from app import models as m

MIGRATIONS = str(Path(__file__).parents[1] / 'migrations')
# Test the underlying migration exception and rollback, without Flask-Migrate's
# CLI-only decorator converting RuntimeError to SystemExit(1).
upgrade = upgrade.__wrapped__
downgrade = downgrade.__wrapped__


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / 'isolated.sqlite3'
    with sqlite3.connect(path) as c:
        c.executescript(Path(__file__).with_name('legacy_schema.sql').read_text(encoding='utf-8'))
        c.execute("INSERT INTO alembic_version VALUES('0001_initial')")
        c.execute("INSERT INTO workspace(id,user_name,name,created_at,updated_at) VALUES('legacy','','initial workspace',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO workspace_setting(id,workspace_id,key,value,created_at,updated_at) VALUES('s','legacy','synthetic','{\"preserve\":true}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    return path


def migration_app(path):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + str(path), SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app); migrate.init_app(app,db,directory=MIGRATIONS)
    with app.app_context():
        @event.listens_for(db.engine,'connect')
        def fk(connection,_record):
            connection.execute('PRAGMA foreign_keys=ON')
    return app


def inventory(path):
    with sqlite3.connect(path) as c:
        names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: c.execute('SELECT * FROM "'+name+'"').fetchall() for name in names}


def test_legacy_upgrade_preserves_rows_fk_indexes_and_integrity(legacy):
    before=inventory(legacy)
    app=migration_app(legacy)
    with app.app_context():
        upgrade(directory=MIGRATIONS)
        from app.storage import SCHEMA_HEAD
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==SCHEMA_HEAD
        assert db.session.execute(text('PRAGMA integrity_check')).scalar_one()=='ok'
        assert not db.session.execute(text('PRAGMA foreign_key_check')).all()
        from sqlalchemy import inspect
        inspector=inspect(db.engine)
        assert set(m.User.__table__.columns.keys())=={x['name'] for x in inspector.get_columns('users')}
        for name in ['users','consents','works','work_documents','document_revisions','essay_documents','feedback_reactions','ai_interactions','app_settings','user_annotations']:
            assert name in inspector.get_table_names()
            assert {c.name for c in db.metadata.tables[name].columns}=={c['name'] for c in inspector.get_columns(name)}
            expected={tuple(c.name for c in fk.columns) for fk in db.metadata.tables[name].foreign_key_constraints}
            assert expected=={tuple(fk['constrained_columns']) for fk in inspector.get_foreign_keys(name)}
        for name in ['writing','analysis','source_document']:
            assert any(i['name'].endswith('owner_id') or i['name'].endswith('essay_version_id') for i in inspector.get_indexes(name))
    after=inventory(legacy)
    assert [r[:-1] for r in after['workspace']]==before['workspace']
    assert after['workspace_setting']==before['workspace_setting']
    assert len(after)==len(before)+10
    assert set(after)-set(before)=={'users','consents','works','work_documents','document_revisions','essay_documents','feedback_reactions','ai_interactions','app_settings','user_annotations'}
    assert after['user_annotations']==[]


def test_upgrade_reexecution_is_noop(legacy):
    app=migration_app(legacy)
    with app.app_context():
        upgrade(directory=MIGRATIONS);before=inventory(legacy)
        upgrade(directory=MIGRATIONS)
        assert inventory(legacy)==before


def test_fresh_initial_to_head_and_entity_crud(tmp_path):
    app=migration_app(tmp_path/'fresh.sqlite3')
    with app.app_context():
        upgrade(directory=MIGRATIONS)
        user=m.User(oidc_issuer='https://accounts.google.com',oidc_subject='synthetic-sub')
        db.session.add(user);db.session.flush()
        assert user.role=='USER' and user.status=='PENDING_APPROVAL'
        user.status='ACTIVE';db.session.add(m.Consent(user_id=user.id,kind='AI',policy_version='test-only'))
        db.session.add(m.AppSetting(key='ai_enabled',value=False));db.session.commit()
        assert m.User.query.one().status=='ACTIVE';assert m.Consent.query.one().policy_version=='test-only'
        assert m.AppSetting.query.one().value is False


def test_unknown_owner_fk_and_unique_subject(legacy):
    app=migration_app(legacy)
    with app.app_context():
        upgrade(directory=MIGRATIONS)
        db.session.add(m.Writing(workspace_id='legacy',owner_id='missing'))
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):db.session.commit()
        db.session.rollback()
        db.session.add_all([m.User(oidc_issuer='i',oidc_subject='s'),m.User(oidc_issuer='i',oidc_subject='s')])
        with pytest.raises(IntegrityError):db.session.commit()
        db.session.rollback()


def test_version_run_and_document_revision_invariants(legacy):
    app=migration_app(legacy)
    with app.app_context():
        upgrade(directory=MIGRATIONS)
        u=m.User(oidc_issuer='i',oidc_subject='s');db.session.add(u);db.session.flush()
        w=m.Writing(workspace_id='legacy',owner_id=u.id,content='가😀');db.session.add(w);db.session.flush()
        v=m.WritingVersion(writing_id=w.id,name='snapshot',content='가😀',version_number=1,snapshot_hash=hashlib.sha256('가😀'.encode()).hexdigest(),normalization_version='nfc-lf/1');db.session.add(v);db.session.commit()
        a=m.Analysis(writing_id=w.id,essay_version_id=v.id);db.session.add(a);db.session.commit()
        from sqlalchemy.exc import IntegrityError
        v.content='changed'
        with pytest.raises(IntegrityError):db.session.commit()
        db.session.rollback()
        d=m.SourceDocument(workspace_id='legacy',title='synthetic',original_name='synthetic.txt',stored_name='synthetic',mime_type='text/plain',size=1,owner_id=u.id,scope='PRIVATE',document_type='TEXT',access_mode='VIEW',rights_confirmed=False);db.session.add(d);db.session.flush()
        r=m.DocumentRevision(document_id=d.id,revision_number=1,content='source',content_hash='a'*64);db.session.add(r);db.session.commit()
        r.content='changed'
        with pytest.raises(IntegrityError):db.session.commit()
        db.session.rollback()
        assert m.WritingVersion.query.one().content=='가😀';assert m.DocumentRevision.query.one().content=='source'


def test_downgrade_refused_and_verified_restore(legacy,tmp_path):
    before=inventory(legacy);backup=tmp_path/'original-backup.sqlite3'
    with sqlite3.connect(legacy) as src,sqlite3.connect(backup) as dst:src.backup(dst)
    app=migration_app(legacy)
    with app.app_context():
        upgrade(directory=MIGRATIONS);after=inventory(legacy)
        with pytest.raises(RuntimeError,match='NONDESTRUCTIVE_DOWNGRADE'):downgrade(directory=MIGRATIONS,revision='0001_initial')
        assert inventory(legacy)==after
    restored=tmp_path/'restored.sqlite3'
    with sqlite3.connect(backup) as src,sqlite3.connect(restored) as dst:src.backup(dst)
    assert inventory(restored)==before


def test_injected_failure_rolls_back_all_ddl(legacy,monkeypatch):
    import alembic.operations.base
    before=inventory(legacy)
    real=alembic.operations.base.Operations.execute
    count=0
    def fail_after_two(self,sql,*args,**kwargs):
        nonlocal count
        count+=1
        if count==3:raise RuntimeError('synthetic migration failure')
        return real(self,sql,*args,**kwargs)
    monkeypatch.setattr(alembic.operations.base.Operations,'execute',fail_after_two)
    app=migration_app(legacy)
    with app.app_context():
        with pytest.raises(RuntimeError,match='synthetic migration failure'):upgrade(directory=MIGRATIONS)
    assert inventory(legacy)==before
