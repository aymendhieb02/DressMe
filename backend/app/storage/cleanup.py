from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import PendingUpload, StorageDeletion, utcnow
from .local_disk import LocalPrivateStorage


def drain_storage_deletions(limit: int = 100, session_factory=SessionLocal, storage_factory=LocalPrivateStorage) -> int:
    """Retry cleanup intents; database rows remain until files are gone."""
    completed = 0
    with session_factory() as db:
        keys = db.scalars(
            select(StorageDeletion).order_by(StorageDeletion.created_at).limit(limit)
        ).all()
        for item in keys:
            try:
                storage_factory().delete(item.image_key)
            except Exception:
                item.attempts += 1
                item.last_attempt_at = datetime.now(timezone.utc)
                db.commit()
                continue
            db.delete(item)
            db.commit()
            completed += 1
    return completed


def acknowledge_storage_deletion(db: Session, image_key: str) -> None:
    item = db.scalar(select(StorageDeletion).where(StorageDeletion.image_key == image_key))
    if item is not None:
        db.delete(item)
        db.commit()


def record_storage_deletion_failure(db: Session, image_key: str) -> None:
    item = db.scalar(select(StorageDeletion).where(StorageDeletion.image_key == image_key))
    if item is not None:
        item.attempts += 1
        item.last_attempt_at = datetime.now(timezone.utc)
        db.commit()


def enqueue_storage_deletion(db: Session, image_key: str) -> None:
    if db.scalar(select(StorageDeletion.id).where(StorageDeletion.image_key == image_key)) is None:
        db.add(StorageDeletion(image_key=image_key))
        db.commit()


def expire_pending_uploads(limit: int = 100) -> int:
    """Revoke abandoned upload references and queue their private files for removal."""
    count = 0
    with SessionLocal() as db:
        rows = db.scalars(
            select(PendingUpload)
            .where(PendingUpload.consumed_at.is_(None), PendingUpload.expires_at <= utcnow())
            .order_by(PendingUpload.expires_at)
            .limit(limit)
        ).all()
        for row in rows:
            if db.scalar(select(StorageDeletion.id).where(StorageDeletion.image_key == row.image_key)) is None:
                db.add(StorageDeletion(image_key=row.image_key))
            db.delete(row)
            count += 1
        db.commit()
    return count
