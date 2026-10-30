"""Add owner-scoped pending uploads and wardrobe records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_wardrobe"
down_revision = "0001_shared_identity"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "pending_uploads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_key", sa.String(64), nullable=False, unique=True),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("quality_snapshot", json_type, nullable=False),
        sa.Column("prediction_snapshot", json_type, nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("taxonomy_version", sa.String(100), nullable=False),
        sa.Column("description_version", sa.String(100), nullable=False),
        sa.Column("quality_version", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pending_uploads_user_id", "pending_uploads", ["user_id"])
    op.create_index("ix_pending_uploads_user_expires", "pending_uploads", ["user_id", "expires_at"])
    op.create_table(
        "garments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pending_upload_id", sa.Uuid(), sa.ForeignKey("pending_uploads.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("image_key", sa.String(64), nullable=False, unique=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("color", sa.String(32)),
        sa.Column("pattern", sa.String(32)),
        sa.Column("sleeve_length", sa.String(32)),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("description_is_manual", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("name", sa.String(120)),
        sa.Column("notes", sa.String(2000)),
        sa.Column("prediction_snapshot", json_type, nullable=False),
        sa.Column("quality_snapshot", json_type, nullable=False),
        sa.Column("field_sources", json_type, nullable=False),
        sa.Column("was_corrected", json_type, nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("taxonomy_version", sa.String(100), nullable=False),
        sa.Column("description_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_garments_user_id", "garments", ["user_id"])
    op.create_index("ix_garments_user_category", "garments", ["user_id", "category"])
    op.create_index("ix_garments_user_color", "garments", ["user_id", "color"])
    op.create_index("ix_garments_user_created", "garments", ["user_id", "created_at"])


def downgrade():
    # Downgrade drops these tables; run only on disposable development databases.
    op.drop_table("garments")
    op.drop_table("pending_uploads")
