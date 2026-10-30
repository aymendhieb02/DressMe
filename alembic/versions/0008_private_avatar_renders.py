"""Add one private, avatar-version-bound render per current avatar."""

from alembic import op
import sqlalchemy as sa


revision = "0008_private_avatar_renders"
down_revision = "0007_private_avatars"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "avatar_renders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("avatar_id", sa.Uuid(), sa.ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_avatar_version", sa.Integer(), nullable=False),
        sa.Column("source_avatar_sha256", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("render_settings", sa.JSON(), nullable=False),
        sa.Column("image_key", sa.String(64), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("renderer_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("avatar_id", name="uq_avatar_renders_avatar_id"),
        sa.UniqueConstraint("image_key", name="uq_avatar_renders_image_key"),
    )
    op.create_index("ix_avatar_renders_user_id", "avatar_renders", ["user_id"])
    op.create_index("ix_avatar_renders_owner_created", "avatar_renders", ["user_id", "created_at"])


def downgrade():
    op.drop_index("ix_avatar_renders_owner_created", table_name="avatar_renders")
    op.drop_index("ix_avatar_renders_user_id", table_name="avatar_renders")
    op.drop_table("avatar_renders")
