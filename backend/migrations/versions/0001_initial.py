"""Initial 글빛 schema."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    from app.extensions import db
    from app import models  # noqa: F401
    db.metadata.create_all(bind=op.get_bind())


def downgrade():
    from app.extensions import db
    from app import models  # noqa: F401
    db.metadata.drop_all(bind=op.get_bind())
