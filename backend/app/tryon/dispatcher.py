import time
from datetime import timedelta

from redis import Redis
from rq import Queue
from rq.exceptions import DuplicateJobError
from rq.job import Job
from rq.serializers import JSONSerializer
from rq.job import JobStatus
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..config import get_settings
from ..database import SessionLocal
from ..models import TryOnAttempt, TryOnJob, TryOnJobOutbox, utcnow
from ..storage.cleanup import drain_storage_deletions, expire_pending_uploads

QUEUE_NAME = "try-on"
MAX_ATTEMPTS = 2
RUN_LEASE_SECONDS = 330
MISSING_QUEUE_JOB_SECONDS = 30


def dispatch_pending(queue: Queue, session_factory: sessionmaker = SessionLocal, limit: int = 100) -> int:
    published = 0
    now = utcnow()
    with session_factory() as db:
        rows = db.scalars(
            select(TryOnJobOutbox)
            .join(TryOnJob, TryOnJob.id == TryOnJobOutbox.job_id)
            .where(
                TryOnJob.state == "queued",
                TryOnJobOutbox.published_at.is_(None),
                TryOnJobOutbox.next_attempt_at <= now,
            )
            .order_by(TryOnJob.created_at)
            .limit(limit)
        ).all()
        for row in rows:
            queue_id = f"tryon-{row.job_id.hex}-{row.delivery_number}"
            try:
                queue.enqueue(
                    "app.tryon.worker_tasks.run_mock_job",
                    str(row.job_id),
                    job_id=queue_id,
                    unique=True,
                    job_timeout=300,
                    ttl=900,
                    result_ttl=86400,
                    failure_ttl=86400,
                )
            except DuplicateJobError:
                pass
            except Exception:
                row.publish_attempts += 1
                row.last_error_code = "redis_unavailable"
                row.next_attempt_at = now + timedelta(seconds=min(60, 2 ** min(row.publish_attempts, 6)))
                continue
            row.published_at = now
            row.delivery_number += 1
            row.last_error_code = None
            published += 1
        db.commit()
    return published


def reconcile_deliveries(redis: Redis, session_factory: sessionmaker = SessionLocal) -> int:
    recovered = 0
    now = utcnow()
    with session_factory() as db:
        rows = db.scalars(
            select(TryOnJobOutbox).join(TryOnJob, TryOnJob.id == TryOnJobOutbox.job_id)
            .where(TryOnJobOutbox.published_at.is_not(None))
        ).all()
        for outbox in rows:
            job = db.get(TryOnJob, outbox.job_id)
            if job is None or job.state not in {"queued", "running"}:
                continue
            delivery_id = f"tryon-{outbox.job_id.hex}-{max(0, outbox.delivery_number - 1)}"
            queued_job = None
            try:
                queued_job = Job.fetch(delivery_id, connection=redis, serializer=JSONSerializer)
                delivery_status = queued_job.get_status(refresh=True)
            except Exception:
                delivery_status = None

            age = (now - outbox.published_at).total_seconds()
            if job.state == "queued":
                if delivery_status == JobStatus.CANCELED:
                    job.state, job.updated_at = "cancelled", now
                    outbox.published_at = None
                    recovered += 1
                elif delivery_status in {JobStatus.FAILED, JobStatus.STOPPED, JobStatus.FINISHED}:
                    outbox.published_at = None
                    outbox.next_attempt_at = now
                    recovered += 1
                elif delivery_status is None and age >= MISSING_QUEUE_JOB_SECONDS:
                    outbox.published_at = None
                    outbox.next_attempt_at = now
                    recovered += 1
                continue

            attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == job.active_attempt_token))
            is_dead = delivery_status in {JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED}
            lease_expired = (now - job.updated_at).total_seconds() >= RUN_LEASE_SECONDS
            if not is_dead and not lease_expired:
                continue
            if attempt is not None:
                attempt.state = "timed_out"
                attempt.error_code = "worker_lost"
                attempt.finished_at = now
            job.active_attempt_token = None
            job.updated_at = now
            if job.cancellation_requested_at is not None or delivery_status == JobStatus.CANCELED:
                job.state = "cancelled"
            elif job.attempt_count < MAX_ATTEMPTS:
                job.state = "queued"
                outbox.published_at = None
                outbox.next_attempt_at = now
                recovered += 1
            else:
                job.state, job.error_code = "timed_out", "worker_lost"
                outbox.published_at = None
        db.commit()
    return recovered


def run_dispatcher() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2, health_check_interval=30)
    queue = Queue(QUEUE_NAME, connection=redis, serializer=JSONSerializer)
    while True:
        try:
            reconcile_deliveries(redis)
            dispatch_pending(queue)
            expire_pending_uploads()
            drain_storage_deletions()
        except Exception:
            # PostgreSQL and Redis outages leave jobs and cleanup intents durable for retry.
            pass
        time.sleep(2)


if __name__ == "__main__":
    run_dispatcher()
