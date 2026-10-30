import time
import uuid
from datetime import datetime, timedelta, timezone

from redis import Redis
from rq import Queue
from rq.exceptions import DuplicateJobError
from rq.job import Job
from rq.serializers import JSONSerializer
from rq.job import JobStatus
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from ..config import get_settings
from ..database import SessionLocal
from ..models import TryOnAttempt, TryOnJob, TryOnJobOutbox, utcnow
from ..storage.cleanup import drain_storage_deletions, expire_pending_uploads
from .adapters import UNSUPPORTED_ADAPTER, supports_mock_profile

QUEUE_NAME = get_settings().tryon_queue_name
MAX_ATTEMPTS = 2
RUN_LEASE_SECONDS = 330
MISSING_QUEUE_JOB_SECONDS = 30
DISPATCHER_LEASE_SECONDS = 12


def _dispatcher_keys(queue_name: str) -> tuple[str, str]:
    prefix = f"dressme:dispatcher:{queue_name}"
    return f"{prefix}:lease", f"{prefix}:heartbeat"


def _refresh_dispatcher_lease(redis: Redis, queue_name: str, token: str) -> bool:
    lease_key, heartbeat_key = _dispatcher_keys(queue_name)
    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        redis.call('EXPIRE', KEYS[1], ARGV[2])
        redis.call('SET', KEYS[2], ARGV[3], 'EX', ARGV[2])
        return 1
    end
    return 0
    """
    return bool(redis.eval(script, 2, lease_key, heartbeat_key, token, DISPATCHER_LEASE_SECONDS, str(time.time())))


def _as_utc(value: datetime) -> datetime:
    # SQLite drops timezone information from DateTime(timezone=True) columns.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


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
            job = db.get(TryOnJob, row.job_id)
            if job is None:
                continue
            if not supports_mock_profile(job.mode, job.settings_snapshot):
                db.execute(
                    update(TryOnJob)
                    .where(TryOnJob.id == row.job_id, TryOnJob.state == "queued")
                    .values(state="failed", error_code=UNSUPPORTED_ADAPTER, updated_at=now)
                    .execution_options(synchronize_session=False)
                )
                row.last_error_code = UNSUPPORTED_ADAPTER
                continue
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

            age = (now - _as_utc(outbox.published_at)).total_seconds()
            if job.state == "queued":
                if delivery_status == JobStatus.CANCELED:
                    result = db.execute(
                        update(TryOnJob)
                        .where(
                            TryOnJob.id == job.id,
                            TryOnJob.state == "queued",
                        )
                        .values(state="cancelled", updated_at=now)
                        .execution_options(synchronize_session=False)
                    )
                    if result.rowcount == 1:
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
            lease_expired = (now - _as_utc(job.updated_at)).total_seconds() >= RUN_LEASE_SECONDS
            if not is_dead and not lease_expired:
                continue
            if job.cancellation_requested_at is not None or delivery_status == JobStatus.CANCELED:
                next_state = "cancelled"
            elif job.attempt_count < MAX_ATTEMPTS:
                next_state = "queued"
            else:
                next_state = "timed_out"
            values = {"state": next_state, "active_attempt_token": None, "updated_at": now}
            if next_state == "timed_out":
                values["error_code"] = "worker_lost"
            # Publication/cancellation may have won while Redis was queried. Recover
            # only the same unchanged attempt, never overwrite its completed result.
            result = db.execute(
                update(TryOnJob)
                .where(
                    TryOnJob.id == job.id,
                    TryOnJob.state == "running",
                    TryOnJob.active_attempt_token == job.active_attempt_token,
                    TryOnJob.updated_at == job.updated_at,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                continue
            if attempt is not None:
                attempt.state = "timed_out"
                attempt.error_code = "worker_lost"
                attempt.finished_at = now
            if next_state == "queued":
                outbox.published_at = None
                outbox.next_attempt_at = now
                recovered += 1
            elif next_state == "timed_out":
                outbox.published_at = None
        db.commit()
    return recovered


def run_dispatcher() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2, health_check_interval=30)
    queue = Queue(settings.tryon_queue_name, connection=redis, serializer=JSONSerializer)
    lease_key, _ = _dispatcher_keys(settings.tryon_queue_name)
    token = uuid.uuid4().hex
    try:
        redis.ping()
        if not redis.set(lease_key, token, nx=True, ex=DISPATCHER_LEASE_SECONDS):
            print("Try-on dispatcher is already active for this queue.", flush=True)
            redis.close()
            return
    except Exception:
        redis.close()
        raise
    while True:
        try:
            if not _refresh_dispatcher_lease(redis, settings.tryon_queue_name, token):
                print("Try-on dispatcher lease was lost; exiting to prevent duplicate dispatchers.", flush=True)
                return
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
