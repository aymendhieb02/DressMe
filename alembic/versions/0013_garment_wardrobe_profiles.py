"""Add the per-garment fields the team wardrobe needs, beside the existing garments table."""
from alembic import op
import sqlalchemy as sa

revision = "0013_garment_wardrobe_profiles"
down_revision = "0012_taste_reactions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "garment_wardrobe_profiles",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("garment_id", sa.Uuid(), sa.ForeignKey("garments.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("super_category", sa.String(length=32)),
        sa.Column("outfit_cat", sa.String(length=16), nullable=False),
        sa.Column("material", sa.String(length=32)),
        sa.Column("season", sa.String(length=16)),
        sa.Column("clip_embedding", sa.LargeBinary()),
        sa.Column("embedding_model", sa.String(length=64)),
        sa.Column("embedding_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("outfit_cat IN ('top','bottom','outer','dress','shoes','bag','other')", name="ck_gwp_cat"),
        sa.CheckConstraint("embedding_status IN ('pending','ready','failed')", name="ck_gwp_status"),
        sqlite_autoincrement=True,  # seq backs a public id, so it must never be reused after a delete
    )
    op.create_index("ix_gwp_user_cat", "garment_wardrobe_profiles", ["user_id", "outfit_cat"])


def downgrade():
    op.drop_index("ix_gwp_user_cat", table_name="garment_wardrobe_profiles")
    op.drop_table("garment_wardrobe_profiles")
