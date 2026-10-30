"""Add consented Avaturn records and one private GLB avatar per account."""

from alembic import op
import sqlalchemy as sa


revision = "0007_private_avatars"
down_revision = "0006_mock_tryon_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "avatar_consents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("consent_version", sa.String(64), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_avatar_consents_user_created", "avatar_consents", ["user_id", "consented_at"])
    op.create_table(
        "avatars",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_id", sa.Uuid(), sa.ForeignKey("avatar_consents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(32), server_default="avaturn", nullable=False),
        sa.Column("provider_avatar_id", sa.String(128), nullable=False),
        sa.Column("asset_key", sa.String(64), nullable=False),
        sa.Column("asset_sha256", sa.String(64), nullable=False),
        sa.Column("asset_size", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_avatars_user_id"),
        sa.UniqueConstraint("asset_key", name="uq_avatars_asset_key"),
    )


def downgrade():
    op.drop_table("avatars")
    op.drop_index("ix_avatar_consents_user_created", table_name="avatar_consents")
    op.drop_table("avatar_consents")
