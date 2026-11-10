"""Mark person photos made from the avatar, so deleting the avatar can delete them too."""
from alembic import op
import sqlalchemy as sa

revision = "0015_person_photo_from_avatar"
down_revision = "0014_jacket_try_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("person_photos", sa.Column("from_avatar", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("person_photos") as batch:
        batch.drop_column("from_avatar")
