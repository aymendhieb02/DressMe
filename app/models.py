from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="USER", server_default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    sessions: Mapped[list["RefreshSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class PasswordRecoveryChallenge(Base):
    """At most one replaceable, single-use recovery challenge for each account."""

    __tablename__ = "password_recovery_challenges"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    code_verifier: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    family_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (Index("ix_auth_sessions_user_id", "user_id"),)


# Compatibility alias: the existing cookie-session routes use this historical name.
AuthSession = RefreshSession


class PendingUpload(Base):
    __tablename__ = "pending_uploads"
    __table_args__ = (Index("ix_pending_uploads_user_expires", "user_id", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    image_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    prediction_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    description_version: Mapped[str] = mapped_column(String(100), nullable=False)
    quality_version: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Garment(Base):
    __tablename__ = "garments"
    __table_args__ = (
        Index("ix_garments_user_category", "user_id", "category"),
        Index("ix_garments_user_color", "user_id", "color"),
        Index("ix_garments_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    pending_upload_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("pending_uploads.id", ondelete="RESTRICT"), unique=True, nullable=False)
    image_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    garment_photo_type: Mapped[str] = mapped_column(String(16), nullable=False, default="flat-lay")
    vton_eligibility: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    vton_eligibility_version: Mapped[str] = mapped_column(String(64), nullable=False, default="bo6-fashn-candidate-v1")
    color: Mapped[str | None] = mapped_column(String(32))
    pattern: Mapped[str | None] = mapped_column(String(32))
    sleeve_length: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    description_is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(String(2000))
    prediction_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    quality_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    field_sources: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    was_corrected: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    description_version: Mapped[str] = mapped_column(String(100), nullable=False)
    description_provenance: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class StorageDeletion(Base):
    __tablename__ = "storage_deletions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PersonPhoto(Base):
    __tablename__ = "person_photos"
    __table_args__ = (Index("ix_person_photos_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    image_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AvatarConsent(Base):
    __tablename__ = "avatar_consents"
    __table_args__ = (Index("ix_avatar_consents_user_created", "user_id", "consented_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Avatar(Base):
    __tablename__ = "avatars"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_avatars_user_id"),
        UniqueConstraint("asset_key", name="uq_avatars_asset_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    consent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("avatar_consents.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="avaturn", server_default="avaturn")
    provider_avatar_id: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_size: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AvatarRender(Base):
    """The latest private, deterministic 2D render derived from an avatar version."""

    __tablename__ = "avatar_renders"
    __table_args__ = (
        UniqueConstraint("avatar_id", name="uq_avatar_renders_avatar_id"),
        UniqueConstraint("image_key", name="uq_avatar_renders_image_key"),
        Index("ix_avatar_renders_owner_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False
    )
    source_avatar_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_avatar_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    render_settings: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    image_key: Mapped[str] = mapped_column(String(64), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TryOnJob(Base):
    __tablename__ = "try_on_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key_hash", name="uq_try_on_jobs_owner_idempotency"),
        CheckConstraint("state IN ('queued','running','succeeded','failed','timed_out','cancelled')", name="ck_try_on_jobs_state"),
        Index("ix_try_on_jobs_user_created", "user_id", "created_at"),
        Index("ix_try_on_jobs_state_updated", "state", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    garment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("garments.id", ondelete="RESTRICT"), nullable=False, index=True)
    person_photo_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("person_photos.id", ondelete="RESTRICT"), nullable=False, index=True)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", server_default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    active_attempt_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    result_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    result_metadata: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TryOnJobOutbox(Base):
    __tablename__ = "try_on_job_outbox"

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("try_on_jobs.id", ondelete="CASCADE"), primary_key=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error_code: Mapped[str | None] = mapped_column(String(64))


class TryOnAttempt(Base):
    __tablename__ = "try_on_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_number", name="uq_try_on_attempt_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("try_on_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_token: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
