"""Add one replaceable, single-use password recovery challenge per user."""

from alembic import op
import sqlalchemy as sa


revision = "0009_password_recovery"
down_revision = "0008_private_avatar_renders"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_recovery_challenges",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("code_verifier", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("password_recovery_challenges")
