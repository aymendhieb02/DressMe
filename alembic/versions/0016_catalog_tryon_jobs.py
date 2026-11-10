"""Allow catalog garments in sequential try-on jobs."""
from alembic import op

revision = "0016_catalog_tryon_jobs"
down_revision = "0015_person_photo_from_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("try_on_jobs") as batch:
        batch.alter_column("garment_id", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("try_on_jobs") as batch:
        batch.alter_column("garment_id", nullable=False)
