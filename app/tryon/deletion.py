from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..models import PersonPhoto, StorageDeletion, TryOnAttempt, TryOnJob, TryOnJobOutbox


def delete_jobs(db: Session, rows: list[TryOnJob]) -> None:
    """Delete job children first so behavior is safe with SQLite and PostgreSQL FK enforcement."""
    for row in rows:
        db.execute(delete(TryOnAttempt).where(TryOnAttempt.job_id == row.id))
        db.execute(delete(TryOnJobOutbox).where(TryOnJobOutbox.job_id == row.id))
        db.delete(row)
    db.flush()


def delete_photos(db: Session, rows: list[PersonPhoto]) -> list[str]:
    """Delete person photos and the jobs made from them. Returns the private files to remove after commit."""
    if not rows:
        return []
    jobs = db.scalars(select(TryOnJob).where(TryOnJob.person_photo_id.in_([row.id for row in rows]))).all()
    keys = [job.result_key for job in jobs if job.result_key] + [row.image_key for row in rows]
    for key in keys:
        db.add(StorageDeletion(image_key=key))
    delete_jobs(db, jobs)
    for row in rows:
        db.delete(row)
    db.flush()
    return keys


def delete_avatar_photos(db: Session, user_id: UUID, current_digest: str | None) -> list[str]:
    """Delete every photo made from this user's avatar.

    Photos saved before migration 0015 are not marked, so the current avatar image's digest finds those.
    """
    made_from_avatar = PersonPhoto.from_avatar.is_(True)
    if current_digest is not None:
        made_from_avatar = or_(made_from_avatar, PersonPhoto.image_sha256 == current_digest)
    return delete_photos(db, db.scalars(select(PersonPhoto).where(PersonPhoto.user_id == user_id, made_from_avatar)).all())
