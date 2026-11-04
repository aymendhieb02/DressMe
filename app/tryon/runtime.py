"""Read-only readiness for the mock try-on queue and its long-lived workers."""

from datetime import datetime, timedelta, timezone

from redis import Redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from ..config import get_settings
from .dispatcher import _dispatcher_keys

WORKER_HEARTBEAT_MAX_AGE = timedelta(seconds=90)
DISPATCHER_HEARTBEAT_MAX_AGE_SECONDS = 12


def tryon_runtime_status() -> dict[str, object]:
    settings = get_settings()
    components = {"broker": False, "dispatcher": False, "worker": False}
    result: dict[str, object] = {
        "status": "unavailable",
        "available": False,
        "queue_name": settings.tryon_queue_name,
        "components": components,
        "reason": "redis_unavailable",
    }
    redis = None
    try:
        redis = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            health_check_interval=30,
        )
        redis.ping()
        components["broker"] = True
        _, heartbeat_key = _dispatcher_keys(settings.tryon_queue_name)
        heartbeat = redis.get(heartbeat_key)
        if heartbeat is not None:
            try:
                heartbeat_age = datetime.now(timezone.utc).timestamp() - float(heartbeat)
                components["dispatcher"] = 0 <= heartbeat_age <= DISPATCHER_HEARTBEAT_MAX_AGE_SECONDS
            except (TypeError, ValueError):
                components["dispatcher"] = False

        queue = Queue(settings.tryon_queue_name, connection=redis, serializer=JSONSerializer)
        now = datetime.now(timezone.utc)
        for worker in Worker.all(queue=queue, serializer=JSONSerializer):
            heartbeat_at = worker.last_heartbeat
            if heartbeat_at is None:
                continue
            if heartbeat_at.tzinfo is None:
                heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
            else:
                heartbeat_at = heartbeat_at.astimezone(timezone.utc)
            age = now - heartbeat_at
            if timedelta(0) <= age <= WORKER_HEARTBEAT_MAX_AGE:
                components["worker"] = True
                break
        result["available"] = all(components.values())
        result["status"] = "available" if result["available"] else "unavailable"
        if not components["dispatcher"]:
            result["reason"] = "dispatcher_unavailable"
        elif not components["worker"]:
            result["reason"] = "worker_unavailable"
        else:
            result["reason"] = None
        return result
    except Exception:
        # Health responses intentionally contain no URL, credentials, or raw
        # connection exception text.
        result["available"] = False
        result["status"] = "unavailable"
        if not components["broker"]:
            result["reason"] = "redis_unavailable"
        elif not components["dispatcher"]:
            result["reason"] = "dispatcher_unavailable"
        else:
            result["reason"] = "worker_unavailable"
        return result
    finally:
        if redis is not None:
            redis.close()
