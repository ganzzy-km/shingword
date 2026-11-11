"""Owner-only annotations; additive, no existing rows are rewritten."""
from alembic import op
import sqlalchemy as sa

revision = '0004_user_annotations'
down_revision = '0003_resource_ownership'
branch_labels = depends_on = None

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        raise RuntimeError('SQLITE_REQUIRED')
    if not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql('BEGIN IMMEDIATE')
    if 'user_annotations' not in sa.inspect(bind).get_table_names():
        op.execute('''CREATE TABLE user_annotations (
          id VARCHAR(36) PRIMARY KEY NOT NULL,
          user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
          writing_id VARCHAR(36) NOT NULL REFERENCES writing(id) ON DELETE CASCADE,
          essay_version_id VARCHAR(36) NOT NULL REFERENCES writing_version(id) ON DELETE CASCADE,
          span_start INTEGER NOT NULL CHECK(span_start>=0),
          span_end INTEGER NOT NULL CHECK(span_end>span_start),
          quote TEXT NOT NULL CHECK(length(quote)>0),
          content TEXT NOT NULL CHECK(length(trim(content))>0 AND length(content)<=5000),
          revision_number INTEGER NOT NULL CHECK(revision_number>0),
          original_anchor JSON NOT NULL,
          created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_user_annotations_writing_id ON user_annotations(writing_id)')
    guard = """WHEN NOT EXISTS(SELECT 1 FROM writing w JOIN writing_version v ON v.writing_id=w.id
      WHERE w.id=NEW.writing_id AND w.owner_id=NEW.user_id AND v.id=NEW.essay_version_id
      AND v.snapshot_hash IS NOT NULL AND NEW.span_start>=0 AND NEW.span_end>NEW.span_start
      AND NEW.span_end<=length(v.content) AND substr(v.content,NEW.span_start+1,NEW.span_end-NEW.span_start)=NEW.quote)
      BEGIN SELECT RAISE(ABORT,'INVALID_ANNOTATION_ANCHOR'); END"""
    for event in ('INSERT','UPDATE'):
        op.execute(f'CREATE TRIGGER IF NOT EXISTS annotation_anchor_{event.lower()} BEFORE {event} ON user_annotations '+guard)
    op.execute("""CREATE TRIGGER IF NOT EXISTS annotation_origin_immutable BEFORE UPDATE ON user_annotations
      WHEN NEW.user_id IS NOT OLD.user_id OR NEW.writing_id IS NOT OLD.writing_id
      OR NEW.original_anchor IS NOT OLD.original_anchor
      BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ANNOTATION_ORIGIN'); END""")

def downgrade():
    raise RuntimeError('NONDESTRUCTIVE_DOWNGRADE_UNAVAILABLE_RESTORE_VERIFIED_BACKUP')
