"""Synthetic tests only. Real DB copy is inspected separately, never mutated."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa

spec = importlib.util.spec_from_file_location('mapping_rehearsal', Path(__file__).parents[1] / 'mapping/rehearsal.py')
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)


@pytest.fixture
def legacy(tmp_path):
    p = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(p) as c:
        c.executescript("""
        CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);
        INSERT INTO alembic_version VALUES('0001_initial');
        CREATE TABLE writing(id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE writing_version(id TEXT PRIMARY KEY, writing_id TEXT REFERENCES writing(id), content TEXT);
        CREATE TABLE analysis(id TEXT PRIMARY KEY, writing_id TEXT REFERENCES writing(id));
        CREATE TABLE source_document(id TEXT PRIMARY KEY, title TEXT);
        INSERT INTO writing VALUES('old','synthetic legacy body');
        INSERT INTO writing_version VALUES('old-v','old','synthetic legacy body');
        INSERT INTO analysis VALUES('old-a','old');
        INSERT INTO source_document VALUES('old-d','synthetic legacy edition');
        """)
    return p


@pytest.fixture
def upgraded(legacy):
    engine = sa.create_engine('sqlite:///' + str(legacy))
    with engine.connect() as c:
        c.exec_driver_sql('PRAGMA foreign_keys=ON')
        c.commit()
        with c.begin():
            mapping.candidate_upgrade(c, isolated=True)
        yield c
    engine.dispose()


def test_additive_preserves_unknown_legacy_ownership_and_version(upgraded):
    assert upgraded.exec_driver_sql('SELECT content,owner_id FROM writing').one() == ('synthetic legacy body', None)
    assert upgraded.exec_driver_sql('SELECT essay_version_id FROM analysis').scalar_one() is None
    assert upgraded.exec_driver_sql('SELECT snapshot_hash FROM writing_version').scalar_one() is None
    assert upgraded.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() == '0001_initial'
    assert upgraded.exec_driver_sql('PRAGMA integrity_check').scalar_one() == 'ok'
    assert upgraded.exec_driver_sql('PRAGMA foreign_key_check').all() == []


def test_owner_fk_and_no_automatic_admin(upgraded):
    upgraded.exec_driver_sql("INSERT INTO users(id,oidc_issuer,oidc_subject) VALUES('u','https://accounts.google.com','synthetic-sub')")
    assert upgraded.exec_driver_sql('SELECT role,status FROM users').one() == ('USER', 'PENDING_APPROVAL')
    with pytest.raises(sa.exc.IntegrityError):
        upgraded.exec_driver_sql("UPDATE writing SET owner_id='missing'")
    upgraded.exec_driver_sql("UPDATE writing SET owner_id='u'")
    with pytest.raises(sa.exc.IntegrityError):
        upgraded.exec_driver_sql("INSERT INTO users(id,oidc_issuer,oidc_subject) VALUES('u2','https://accounts.google.com','synthetic-sub')")


def test_certified_version_immutable_and_run_matches_essay(upgraded):
    upgraded.exec_driver_sql("INSERT INTO writing VALUES('other','other draft',NULL)")
    upgraded.exec_driver_sql("INSERT INTO writing_version VALUES('new-v','old','new synthetic body','synthetic-hash','nfc-lf/1')")
    upgraded.exec_driver_sql("INSERT INTO analysis(id,writing_id,essay_version_id) VALUES('new-a','old','new-v')")
    for sql in ["UPDATE writing_version SET content='changed' WHERE id='new-v'", "INSERT INTO analysis(id,writing_id,essay_version_id) VALUES('bad','other','new-v')", "INSERT INTO analysis(id,writing_id,essay_version_id) VALUES('untrusted','old','old-v')"]:
        with pytest.raises(sa.exc.IntegrityError):
            upgraded.exec_driver_sql(sql)
    assert upgraded.exec_driver_sql("SELECT content FROM writing_version WHERE id='new-v'").scalar_one() == 'new synthetic body'


def test_document_revision_append_only(upgraded):
    upgraded.exec_driver_sql("INSERT INTO document_revisions VALUES('r1','old-d',NULL,'synthetic source','hash',1)")
    upgraded.exec_driver_sql("INSERT INTO document_revisions VALUES('r2','old-d','r1','new source','newhash',2)")
    with pytest.raises(sa.exc.IntegrityError):
        upgraded.exec_driver_sql("UPDATE document_revisions SET content='changed' WHERE id='r1'")
    with pytest.raises(sa.exc.IntegrityError):
        upgraded.exec_driver_sql("INSERT INTO document_revisions VALUES('r3','old-d',NULL,'duplicate','h',2)")


def test_backup_restore_never_overwrites_and_keeps_source(legacy,tmp_path):
    before = legacy.read_bytes()
    backup = tmp_path / 'backup.sqlite3'; restored = tmp_path / 'restore.sqlite3'
    mapping.readonly_backup(legacy,backup);mapping.readonly_backup(backup,restored)
    with sqlite3.connect(restored) as c:
        assert c.execute('SELECT content FROM writing').fetchone()[0] == 'synthetic legacy body'
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    with pytest.raises(ValueError):
        mapping.readonly_backup(legacy,backup)
    assert legacy.read_bytes() == before


def test_fail_closed_and_explicit_transaction_rollback(legacy):
    engine = sa.create_engine('sqlite:///' + str(legacy))
    with engine.connect() as c:
        with pytest.raises(ValueError):
            mapping.candidate_upgrade(c)
        c.rollback()
        c.exec_driver_sql('BEGIN IMMEDIATE')
        mapping.candidate_upgrade(c,isolated=True)
        c.rollback()
        assert 'users' not in sa.inspect(c).get_table_names()
        assert c.exec_driver_sql('SELECT content FROM writing').scalar_one() == 'synthetic legacy body'
        c.exec_driver_sql("UPDATE alembic_version SET version_num='unknown'")
        with pytest.raises(ValueError):
            mapping.candidate_upgrade(c,isolated=True)
    engine.dispose()
