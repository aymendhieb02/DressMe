"""Persist garment photo type, description provenance and eligibility decision."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_garment_vton_review"
down_revision = "0003_refresh_families"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.add_column("garments", sa.Column("garment_photo_type", sa.String(16), nullable=False, server_default="flat-lay"))
    op.add_column("garments", sa.Column("vton_eligibility", json_type, nullable=False, server_default=sa.text("'{}'")))
    op.add_column("garments", sa.Column("vton_eligibility_version", sa.String(64), nullable=False, server_default="bo6-fashn-candidate-v1"))
    op.add_column("garments", sa.Column("description_provenance", json_type, nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    # The added review fields are dropped; use only on a disposable development DB.
    op.drop_column("garments", "description_provenance")
    op.drop_column("garments", "vton_eligibility_version")
    op.drop_column("garments", "vton_eligibility")
    op.drop_column("garments", "garment_photo_type")
