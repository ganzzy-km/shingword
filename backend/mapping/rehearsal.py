"""Sandbox-only additive mapping experiment, NOT a registered migration.

Existing Alembic revision stays 0001_initial. Production adoption requires
an explicit reviewed revision. No ownership or historical version backfill.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def inventory(connection):
    """Return metadata and counts only, never user row values."""
    names = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    result = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        result[name] = {
            'count': connection.execute('SELECT count(*) FROM ' + quoted).fetchone()[0],
            'columns': [list(r) for r in connection.execute('PRAGMA table_info(' + quoted + ')')],
            'fks': [list(r) for r in connection.execute('PRAGMA foreign_key_list(' + quoted + ')')],
            'indexes': [list(r) for r in connection.execute('PRAGMA index_list(' + quoted + ')')],
        }
    return result


def readonly_backup(source: Path, destination: Path):
    """SQLite backup API, source opened ro; never overwrite a destination."""
    if not source.is_file() or destination.exists() or source.resolve() == destination.resolve():
        raise ValueError('SOURCE_REQUIRED_OR_DESTINATION_EXISTS')
    # Exclusive placeholder prevents accidentally replacing an existing file.
    with destination.open('xb'):
        pass
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
        src.execute('PRAGMA query_only=ON')
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def candidate_upgrade(connection, *, isolated=False):
    """Exercise ONLY key mapping constraints in an explicitly isolated DB.

    No runtime models/routes are registered; remaining entities are specified
    in DB_MAPPING_PLAN. This is a migration design spike, not full P03.
    """
    if not isolated:
        raise ValueError('ISOLATED_REHEARSAL_REQUIRED')
    revision = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
    if revision != '0001_initial':
        raise ValueError('UNEXPECTED_REVISION')
    inspector = sa.inspect(connection)
    if 'users' in inspector.get_table_names():
        raise ValueError('CANDIDATE_ALREADY_APPLIED')
    op = Operations(MigrationContext.configure(connection))
    op.create_table('users', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('oidc_issuer', sa.Text, nullable=False), sa.Column('oidc_subject', sa.Text, nullable=False),
        sa.Column('role', sa.Text, nullable=False, server_default='USER'),
        sa.Column('status', sa.Text, nullable=False, server_default='PENDING_APPROVAL'),
        sa.Column('session_version', sa.Integer, nullable=False, server_default='0'),
        sa.UniqueConstraint('oidc_issuer', 'oidc_subject'),
        sa.CheckConstraint("role IN ('USER','ADMIN')"),
        sa.CheckConstraint("status IN ('PENDING_APPROVAL','ACTIVE','INACTIVE')"))
    for table in ['writing', 'source_document']:
        # SQLite accepts a nullable inline REFERENCES column; Alembic's
        # add_column(ForeignKey) attempts unsupported ALTER ADD CONSTRAINT.
        # Fixed internal identifiers only; no caller-controlled SQL names.
        op.execute(f'ALTER TABLE {table} ADD COLUMN owner_id VARCHAR(36) REFERENCES users(id) ON DELETE RESTRICT')
        op.create_index('ix_' + table + '_owner_id', table, ['owner_id'])
    op.add_column('writing_version', sa.Column('snapshot_hash', sa.String(64)))
    op.add_column('writing_version', sa.Column('normalization_version', sa.Text))
    op.execute('ALTER TABLE analysis ADD COLUMN essay_version_id VARCHAR(36) REFERENCES writing_version(id) ON DELETE RESTRICT')
    op.add_column('analysis', sa.Column('result_snapshot', sa.JSON))
    op.create_index('ix_analysis_essay_version_id', 'analysis', ['essay_version_id'])
    # Legacy rows remain nullable/untrusted. New certified snapshots cannot be
    # edited; explicit retention deletion is deliberately not implemented here.
    connection.exec_driver_sql("""CREATE TRIGGER certified_version_no_update BEFORE UPDATE ON writing_version
        WHEN OLD.snapshot_hash IS NOT NULL BEGIN SELECT RAISE(ABORT,'IMMUTABLE_VERSION'); END""")
    for event in ['INSERT', 'UPDATE']:
        connection.exec_driver_sql(f"""CREATE TRIGGER analysis_same_essay_{event.lower()} BEFORE {event} ON analysis
            WHEN NEW.essay_version_id IS NOT NULL AND NOT EXISTS(
              SELECT 1 FROM writing_version v WHERE v.id=NEW.essay_version_id
              AND v.writing_id=NEW.writing_id AND v.snapshot_hash IS NOT NULL)
            BEGIN SELECT RAISE(ABORT,'UNTRUSTED_OR_FOREIGN_VERSION'); END""")
    op.create_table('document_revisions', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('source_document.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('parent_id', sa.String(36), sa.ForeignKey('document_revisions.id', ondelete='RESTRICT')),
        sa.Column('content', sa.Text, nullable=False), sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('revision_number', sa.Integer, nullable=False),
        sa.UniqueConstraint('document_id', 'revision_number'))
    connection.exec_driver_sql("""CREATE TRIGGER document_revision_no_update BEFORE UPDATE ON document_revisions
        BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_REVISION'); END""")
