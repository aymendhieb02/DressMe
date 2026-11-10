"""Allow jackets in try-on. Eligibility is stored per garment, so saved jackets are updated too."""
from alembic import op
import sqlalchemy as sa

revision = "0014_jacket_try_on"
down_revision = "0013_garment_wardrobe_profiles"
branch_labels = None
depends_on = None

OLD_POLICY = "bo6-fashn-candidate-v1"
NEW_POLICY = "bo6-fashn-candidate-v2"
garments = sa.table(
    "garments",
    sa.column("id", sa.Uuid()),
    sa.column("category", sa.String()),
    sa.column("garment_photo_type", sa.String()),
    sa.column("vton_eligibility", sa.JSON()),
    sa.column("vton_eligibility_version", sa.String()),
)


def _rewrite(eligibility, policy):
    bind = op.get_bind()
    rows = bind.execute(sa.select(garments.c.id, garments.c.garment_photo_type).where(garments.c.category == "jacket")).all()
    for garment_id, photo_type in rows:
        bind.execute(
            garments.update().where(garments.c.id == garment_id).values(
                vton_eligibility=eligibility(photo_type), vton_eligibility_version=policy,
            )
        )


def _allowed(photo_type):
    supported = photo_type in {"flat-lay", "model"}
    return {
        "status": "disabled" if supported else "blocked",
        "eligible": False,
        "candidate_category": "tops",
        "reason": "mapping_not_visually_validated" if supported else "unsupported_photo_type",
        "policy_version": NEW_POLICY,
    }


def _refused(photo_type):
    return {
        "status": "blocked",
        "eligible": False,
        "candidate_category": None,
        "reason": "unsupported_category" if photo_type in {"flat-lay", "model"} else "unsupported_photo_type",
        "policy_version": OLD_POLICY,
    }


def upgrade():
    _rewrite(_allowed, NEW_POLICY)


def downgrade():
    _rewrite(_refused, OLD_POLICY)
