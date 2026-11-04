"""Limit account gender choices to men/women, preserving unknown legacy values."""
from alembic import op
import sqlalchemy as sa

revision = "0011_binary_account_gender"
down_revision = "0010_user_gender"
branch_labels = None
depends_on = None


def upgrade():
    # Do not invent a male/female choice for existing users.
    op.execute(sa.text("UPDATE users SET gender = NULL WHERE gender = 'unisex'"))
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('ck_users_gender', type_='check')
        batch.create_check_constraint('ck_users_gender', "gender IS NULL OR gender IN ('men', 'women')")


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('ck_users_gender', type_='check')
        batch.create_check_constraint('ck_users_gender', "gender IS NULL OR gender IN ('men', 'women', 'unisex')")
