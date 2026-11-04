"""Persist Taste Studio reactions by account and stable catalog item ID."""
from alembic import op
import sqlalchemy as sa

revision = "0012_taste_reactions"
down_revision = "0011_binary_account_gender"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "taste_reactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("reaction", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "item_id", name="uq_taste_reactions_user_item"),
        sa.CheckConstraint("reaction IN ('like', 'dislike', 'save', 'seen')", name="ck_taste_reaction"),
    )
    op.create_index("ix_taste_reactions_user_reaction", "taste_reactions", ["user_id", "reaction"])


def downgrade():
    op.drop_index("ix_taste_reactions_user_reaction", table_name="taste_reactions")
    op.drop_table("taste_reactions")
