from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import TryOnAttempt, TryOnJob, TryOnJobOutbox


def delete_jobs(db: Session, rows: list[TryOnJob]) -> None:
    """Delete job children first so behavior is safe with SQLite and PostgreSQL FK enforcement."""
    for row in rows:
        db.execute(delete(TryOnAttempt).where(TryOnAttempt.job_id == row.id))
        db.execute(delete(TryOnJobOutbox).where(TryOnJobOutbox.job_id == row.id))
        db.delete(row)
    db.flush()
