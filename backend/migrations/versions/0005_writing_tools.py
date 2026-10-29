"""Add private writing metadata; never rewrite S4, OCR text or old anchors."""
from alembic import op
import sqlalchemy as sa

revision='0005_writing_tools'
down_revision='0004_user_annotations'
branch_labels=depends_on=None


def upgrade():
    bind=op.get_bind()
    if bind.dialect.name!='sqlite':raise RuntimeError('SQLITE_REQUIRED')
    if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
    # The existing0001 bootstrap creates current metadata on a genuinely new DB.
    # Existing0004 DBs need the additions; validate bootstrap columns, don't add twice.
    def ensure(table,column):
        found=next((x for x in sa.inspect(bind).get_columns(table) if x['name']==column.name),None)
        if not found:op.add_column(table,column)
        elif str(found['type']).upper()!=str(column.type).upper() or found['nullable']!=column.nullable:
            raise RuntimeError('UNEXPECTED_WRITING_TOOLS_SCHEMA')
    ensure('user_annotations',sa.Column('annotation_kind',sa.String(24),nullable=False,server_default='NOTE'))
    ensure('user_annotations',sa.Column('metadata_json',sa.JSON))
    ensure('quote_card',sa.Column('metadata_json',sa.JSON))
    ensure('quote_card',sa.Column('revision_number',sa.Integer,nullable=False,server_default='1'))
    ensure('quote_card',sa.Column('client_key',sa.String(64)))
    unique=sa.inspect(bind).get_unique_constraints('quote_card')+sa.inspect(bind).get_indexes('quote_card')
    if not any(x.get('unique',True) and x['column_names']==['owner_id','client_key'] for x in unique):
        op.create_index('uq_quote_owner_client','quote_card',['owner_id','client_key'],unique=True)
    # Reuse the existing essay deletion graph, including expiry and account erasure.
    # Only new cards explicitly bound to that essay are removed; work-only/legacy cards remain.
    trigger="""CREATE TRIGGER writing_tools_essay_cards_delete BEFORE DELETE ON writing
    BEGIN DELETE FROM quote_card WHERE CASE WHEN json_valid(metadata_json)
    THEN json_extract(metadata_json,'$.writingId') END=OLD.id; END"""
    existing=bind.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='writing_tools_essay_cards_delete'").scalar()
    if existing is None:bind.exec_driver_sql(trigger)
    elif ' '.join(existing.split())!=' '.join(trigger.split()):raise RuntimeError('UNEXPECTED_WRITING_TOOLS_TRIGGER')
    if 'publication_requests' in sa.inspect(bind).get_table_names():
        expected={'id','owner_id','document_id','revision_id','revision_hash','state','rights_basis','revision_number','history','created_at','updated_at'}
        if {x['name'] for x in sa.inspect(bind).get_columns('publication_requests')}!=expected:raise RuntimeError('UNEXPECTED_PUBLICATION_SCHEMA')
        return
    op.create_table('publication_requests',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('owner_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('document_id',sa.String(36),sa.ForeignKey('source_document.id',ondelete='CASCADE'),nullable=False),
        sa.Column('revision_id',sa.String(36),sa.ForeignKey('document_revisions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('revision_hash',sa.String(64),nullable=False),
        sa.Column('state',sa.String(20),nullable=False),sa.Column('rights_basis',sa.Text,nullable=False),
        sa.Column('revision_number',sa.Integer,nullable=False),sa.Column('history',sa.JSON,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('owner_id','document_id','revision_id',name='uq_publication_target'),
        sa.CheckConstraint("state IN ('PENDING','APPROVED','REJECTED','WITHDRAWN')"),sa.CheckConstraint('revision_number>0'))


def downgrade():
    bind=op.get_bind()
    # New private data must be exported/handled explicitly, never dropped by rollback.
    if (bind.exec_driver_sql("SELECT 1 FROM user_annotations WHERE annotation_kind!='NOTE' OR (metadata_json IS NOT NULL AND metadata_json!='null') LIMIT 1").first()
        or bind.exec_driver_sql("SELECT 1 FROM quote_card WHERE (metadata_json IS NOT NULL AND metadata_json!='null') OR client_key IS NOT NULL LIMIT 1").first()
        or bind.exec_driver_sql('SELECT 1 FROM publication_requests LIMIT 1').first()):
        raise RuntimeError('WRITING_TOOLS_DATA_REQUIRES_EXPLICIT_PRESERVATION')
    op.execute('DROP TRIGGER writing_tools_essay_cards_delete')
    op.drop_table('publication_requests')
    op.drop_index('uq_quote_owner_client',table_name='quote_card')
    for table, columns in [('quote_card',['client_key','revision_number','metadata_json']),('user_annotations',['metadata_json','annotation_kind'])]:
        for name in columns:op.drop_column(table,name)
