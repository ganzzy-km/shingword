"""Independent, version-bound structure results. Existing S4 rows are untouched."""
from alembic import op
import sqlalchemy as sa

revision = '0006_dual_structure'
down_revision = '0005_writing_tools'
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        raise RuntimeError('SQLITE_REQUIRED')
    if not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql('BEGIN IMMEDIATE')
    existing = set(sa.inspect(bind).get_table_names()) & {'essay_structure_maps', 'essay_structure_runs'}
    if existing:
        # 0001 creates current metadata on an empty installation.
        from app.models import EssayStructureMap, EssayStructureRun
        if len(existing) != 2:
            raise RuntimeError('UNEXPECTED_DUAL_STRUCTURE_SCHEMA')
        for table in (EssayStructureMap.__table__, EssayStructureRun.__table__):
            inspector = sa.inspect(bind)
            if ({column['name'] for column in inspector.get_columns(table.name)} != set(table.columns.keys())
                    or {index['name'] for index in inspector.get_indexes(table.name)} != {index.name for index in table.indexes}
                    or len(inspector.get_foreign_keys(table.name)) != len(table.foreign_keys)):
                raise RuntimeError('UNEXPECTED_DUAL_STRUCTURE_SCHEMA')
        return
    op.create_table('essay_structure_maps',
        sa.Column('version_id', sa.String(36), sa.ForeignKey('writing_version.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('body_hash', sa.String(64), nullable=False),
        sa.Column('map_version', sa.String(40), nullable=False),
        sa.Column('sentence_map', sa.JSON), sa.Column('quotation_ranges', sa.JSON),
        sa.Column('protected_source', sa.Boolean, server_default='0', nullable=False))
    op.create_table('essay_structure_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('writing_id', sa.String(36), sa.ForeignKey('writing.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_id', sa.String(36), sa.ForeignKey('writing_version.id', ondelete='CASCADE'), nullable=False),
        sa.Column('body_hash', sa.String(64), nullable=False), sa.Column('cache_key', sa.String(64), nullable=False),
        sa.Column('engine', sa.String(8), nullable=False), sa.Column('provider', sa.String(24), nullable=False),
        sa.Column('model', sa.String(128), nullable=False), sa.Column('prompt_version', sa.String(40), nullable=False),
        sa.Column('settings', sa.JSON, nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('result', sa.JSON), sa.Column('usage', sa.JSON),
        sa.Column('reserved_cost_units', sa.Integer, nullable=False), sa.Column('error_code', sa.String(48)),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("engine='AI' AND status IN ('QUEUED','RUNNING','COMPLETED','FAILED','REVIEW_REQUIRED')"),
        sa.CheckConstraint('reserved_cost_units>0'))
    op.create_index('ix_structure_run_version_owner', 'essay_structure_runs', ['version_id', 'user_id', 'created_at'])
    op.create_index('ix_structure_run_active', 'essay_structure_runs', ['status', 'deadline_at'])
    op.create_index('uq_structure_run_cache_active', 'essay_structure_runs', ['cache_key'], unique=True,
                    sqlite_where=sa.text("status IN ('QUEUED','RUNNING','COMPLETED')"))


def downgrade():
    bind = op.get_bind()
    for table in ('essay_structure_runs', 'essay_structure_maps'):
        if bind.exec_driver_sql(f'SELECT 1 FROM {table} LIMIT 1').first():
            raise RuntimeError('DUAL_STRUCTURE_DATA_REQUIRES_EXPLICIT_PRESERVATION')
    op.drop_table('essay_structure_runs')
    op.drop_table('essay_structure_maps')
