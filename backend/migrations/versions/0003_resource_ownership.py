"""Nullable ownership for legacy workspace, criteria and quote cards.

Legacy rows remain ownerless and inaccessible through private APIs.
No table recreation/backfill; 0001 and 0002 stay unchanged.
"""
import sqlalchemy as sa
from alembic import op

revision='0003_resource_ownership'
down_revision='0002_geulbit_v2'
branch_labels=None
depends_on=None


def upgrade():
    bind=op.get_bind()
    if bind.dialect.name!='sqlite':raise RuntimeError('SQLITE_REQUIRED')
    if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
    for name in ['workspace','rubric','quote_card']:
        columns={c['name'] for c in sa.inspect(bind).get_columns(name)}
        if 'owner_id' not in columns:op.execute('ALTER TABLE '+name+' ADD COLUMN owner_id VARCHAR(36) REFERENCES users(id) ON DELETE RESTRICT')
        op.execute('CREATE INDEX IF NOT EXISTS ix_'+name+'_owner_id ON '+name+'(owner_id)')
        op.execute('CREATE TRIGGER IF NOT EXISTS v3_'+name+'_owner_no_transfer BEFORE UPDATE OF owner_id ON '+name+" WHEN OLD.owner_id IS NOT NULL AND NEW.owner_id IS NOT OLD.owner_id BEGIN SELECT RAISE(ABORT,'OWNER_TRANSFER_FORBIDDEN'); END")
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_owner ON workspace(owner_id) WHERE owner_id IS NOT NULL')


def downgrade():raise RuntimeError('NONDESTRUCTIVE_DOWNGRADE_UNAVAILABLE_RESTORE_VERIFIED_BACKUP')
