"""Fresh 0003 copy: additive upgrade, retry, transaction rollback and safe restore."""
from pathlib import Path
import sqlite3
import pytest
from flask import Flask
from flask_migrate import upgrade,downgrade
import v2_fixture  # Existing backend import-path/bootstrap contract.
from app.extensions import db,migrate
from sqlalchemy import text

def existing_0003():
    # Historic 0001 creates current metadata on a *fresh test DB*. Remove only
    # the empty new table here to reproduce an already-existing 0003 database.
    upgrade(revision='0003_resource_ownership')
    db.session.execute(text('DROP TABLE user_annotations'));db.session.commit()

def test_additive_upgrade_preserves_all_existing_rows_and_restore(tmp_path):
    path=tmp_path/'isolated.sqlite3'
    app=Flask('annotation-migration');app.config['SQLALCHEMY_DATABASE_URI']='sqlite:///'+str(path)
    db.init_app(app);migrate.init_app(app,db,directory=str(Path(__file__).parents[1]/'migrations'))
    with app.app_context():
        existing_0003()
        with sqlite3.connect(path) as c:
            c.execute("INSERT INTO app_settings(key,value,created_at,updated_at) VALUES('annotation-preservation','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        with sqlite3.connect(path) as source,sqlite3.connect(tmp_path/'restore.sqlite3') as backup:source.backup(backup)
        with sqlite3.connect(path) as c:
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='alembic_version'")]
            before={t:c.execute('SELECT * FROM "'+t+'"').fetchall() for t in tables}
        upgrade()
        upgrade() # idempotent Alembic head, not re-running destructive SQL
        with sqlite3.connect(path) as c:
            assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('0004_user_annotations',)
            assert {t:c.execute('SELECT * FROM "'+t+'"').fetchall() for t in tables}==before
            assert c.execute('PRAGMA integrity_check').fetchone()==('ok',)
            assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
            assert len(c.execute('PRAGMA foreign_key_list(user_annotations)').fetchall())==3
            assert 'ix_user_annotations_writing_id' in [r[1] for r in c.execute('PRAGMA index_list(user_annotations)')]
        with pytest.raises(SystemExit) as failure:downgrade(revision='0003_resource_ownership')
        assert failure.value.code==1
        db.session.remove();db.engine.dispose()
        with sqlite3.connect(tmp_path/'restore.sqlite3') as backup,sqlite3.connect(path) as target:backup.backup(target)
        with sqlite3.connect(path) as c:
            assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('0003_resource_ownership',)
            assert {t:c.execute('SELECT * FROM "'+t+'"').fetchall() for t in tables}==before

def test_failed_additive_upgrade_rolls_back_then_retry(tmp_path,monkeypatch):
    import alembic.op
    path=tmp_path/'failure.sqlite3';app=Flask('annotation-failure');app.config['SQLALCHEMY_DATABASE_URI']='sqlite:///'+str(path)
    db.init_app(app);migrate.init_app(app,db,directory=str(Path(__file__).parents[1]/'migrations'))
    with app.app_context():
        existing_0003()
        real=alembic.op.execute
        def fail_after_table(sql,*args,**kwargs):
            if 'CREATE INDEX IF NOT EXISTS ix_user_annotations' in str(sql):raise RuntimeError('SYNTHETIC_MIGRATION_FAILURE')
            return real(sql,*args,**kwargs)
        with monkeypatch.context() as m:
            m.setattr(alembic.op,'execute',fail_after_table)
            with pytest.raises(RuntimeError,match='SYNTHETIC_MIGRATION_FAILURE'):upgrade.__wrapped__()
        with sqlite3.connect(path) as c:
            assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('0003_resource_ownership',)
            assert not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_annotations'").fetchall()
            assert c.execute('PRAGMA integrity_check').fetchone()==('ok',)
        upgrade()
        with sqlite3.connect(path) as c:assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('0004_user_annotations',)
