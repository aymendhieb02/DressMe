"""Add private person photos and durable mock try-on jobs/outbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_mock_tryon_jobs"
down_revision = "0005_storage_deletion_outbox"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "person_photos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_key", sa.String(64), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("consent_version", sa.String(64), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("image_key", name="uq_person_photos_image_key"),
    )
    op.create_index("ix_person_photos_user_id", "person_photos", ["user_id"])
    op.create_index("ix_person_photos_user_created", "person_photos", ["user_id", "created_at"])

    op.create_table(
        "try_on_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("garment_id", sa.Uuid(), sa.ForeignKey("garments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("person_photo_id", sa.Uuid(), sa.ForeignKey("person_photos.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active_attempt_token", sa.Uuid()),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True)),
        sa.Column("settings_snapshot", json_type, nullable=False),
        sa.Column("input_snapshot", json_type, nullable=False),
        sa.Column("result_key", sa.String(64)),
        sa.Column("result_metadata", json_type),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key_hash", name="uq_try_on_jobs_owner_idempotency"),
        sa.UniqueConstraint("result_key", name="uq_try_on_jobs_result_key"),
        sa.CheckConstraint("state IN ('queued','running','succeeded','failed','timed_out','cancelled')", name="ck_try_on_jobs_state"),
    )
    for table, column in (("try_on_jobs", "user_id"), ("try_on_jobs", "garment_id"), ("try_on_jobs", "person_photo_id")):
        op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index("ix_try_on_jobs_user_created", "try_on_jobs", ["user_id", "created_at"])
    op.create_index("ix_try_on_jobs_state_updated", "try_on_jobs", ["state", "updated_at"])

    op.create_table(
        "try_on_job_outbox",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("try_on_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
    )
    op.create_table(
        "try_on_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("try_on_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("attempt_token", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_try_on_attempt_number"),
        sa.UniqueConstraint("attempt_token", name="uq_try_on_attempts_attempt_token"),
    )
    op.create_index("ix_try_on_attempts_job_id", "try_on_attempts", ["job_id"])


def downgrade():
    # This removes photo/job history and queued dispatch intent; use only on disposable DBs.
    op.drop_index("ix_try_on_attempts_job_id", table_name="try_on_attempts")
    op.drop_table("try_on_attempts")
    op.drop_table("try_on_job_outbox")
    op.drop_index("ix_try_on_jobs_state_updated", table_name="try_on_jobs")
    op.drop_index("ix_try_on_jobs_user_created", table_name="try_on_jobs")
    op.drop_index("ix_try_on_jobs_person_photo_id", table_name="try_on_jobs")
    op.drop_index("ix_try_on_jobs_garment_id", table_name="try_on_jobs")
    op.drop_index("ix_try_on_jobs_user_id", table_name="try_on_jobs")
    op.drop_table("try_on_jobs")
    op.drop_index("ix_person_photos_user_created", table_name="person_photos")
    op.drop_index("ix_person_photos_user_id", table_name="person_photos")
    op.drop_table("person_photos")
