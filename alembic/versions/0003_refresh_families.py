"""Record refresh-token rotation families."""
from alembic import op
import sqlalchemy as sa

revision = "0003_refresh_families"
down_revision = "0002_wardrobe"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable during adoption so an existing development session remains readable;
    # the first successful refresh assigns its legacy session ID as the family ID.
    op.add_column("auth_sessions", sa.Column("family_id", sa.Uuid(), nullable=True))
    op.create_index("ix_auth_sessions_family_id", "auth_sessions", ["family_id"])


def downgrade():
    op.drop_index("ix_auth_sessions_family_id", table_name="auth_sessions")
    op.drop_column("auth_sessions", "family_id")
