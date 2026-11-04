"""Persist the user's optional clothing gender without changing existing accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0010_user_gender"
down_revision = "0009_password_recovery"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("gender", sa.String(8), nullable=True))
        batch.create_check_constraint("ck_users_gender", "gender IS NULL OR gender IN ('men', 'women', 'unisex')")


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_gender", type_="check")
        batch.drop_column("gender")
