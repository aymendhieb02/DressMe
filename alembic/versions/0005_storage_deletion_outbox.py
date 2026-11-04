"""Retain private-file cleanup intent after database rows are deleted."""
from alembic import op
import sqlalchemy as sa


revision = "0005_storage_deletion_outbox"
down_revision = "0004_garment_vton_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "storage_deletions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("image_key", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("image_key", name="uq_storage_deletions_image_key"),
    )
    op.create_index("ix_storage_deletions_created_at", "storage_deletions", ["created_at"])


def downgrade():
    # Downgrade would discard pending cleanup work; run only on disposable databases.
    op.drop_index("ix_storage_deletions_created_at", table_name="storage_deletions")
    op.drop_table("storage_deletions")
