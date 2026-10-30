from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from redis.exceptions import ConnectionError as RedisConnectionError

from app import main
from app.tryon import runtime


class FakeRedis:
    def __init__(self, heartbeat=None, error=None):
        self.heartbeat = heartbeat
        self.error = error
        self.closed = False

    def ping(self):
        if self.error:
            raise self.error

    def get(self, key):
        assert key == "dressme:dispatcher:try-on-demo:heartbeat"
        return self.heartbeat

    def close(self):
        self.closed = True


def test_tryon_runtime_requires_live_broker_dispatcher_and_worker(monkeypatch):
    now = datetime.now(timezone.utc)
    broker = FakeRedis(str(now.timestamp()))
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(
        redis_url="redis://safe-placeholder", tryon_queue_name="try-on-demo"
    ))
    monkeypatch.setattr(runtime.Redis, "from_url", lambda *_args, **_kwargs: broker)
    monkeypatch.setattr(runtime, "Queue", lambda name, **_kwargs: SimpleNamespace(name=name))
    monkeypatch.setattr(runtime.Worker, "all", lambda **kwargs: [
        SimpleNamespace(last_heartbeat=now - timedelta(seconds=10))
    ])

    status = runtime.tryon_runtime_status()

    assert status == {
        "status": "available", "available": True, "queue_name": "try-on-demo",
        "components": {"broker": True, "dispatcher": True, "worker": True}, "reason": None,
    }
    assert broker.closed


def test_tryon_runtime_rejects_missing_or_stale_workers(monkeypatch):
    now = datetime.now(timezone.utc)
    broker = FakeRedis(str(now.timestamp()))
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(
        redis_url="redis://safe-placeholder", tryon_queue_name="try-on-demo"
    ))
    monkeypatch.setattr(runtime.Redis, "from_url", lambda *_args, **_kwargs: broker)
    monkeypatch.setattr(runtime, "Queue", lambda name, **_kwargs: SimpleNamespace(name=name))
    monkeypatch.setattr(runtime.Worker, "all", lambda **kwargs: [
        SimpleNamespace(last_heartbeat=now - timedelta(seconds=120))
    ])

    status = runtime.tryon_runtime_status()

    assert status["available"] is False
    assert status["components"] == {"broker": True, "dispatcher": True, "worker": False}
    assert status["reason"] == "worker_unavailable"


def test_tryon_runtime_reports_broker_failure_without_leaking_connection_details(monkeypatch):
    broker = FakeRedis(error=RedisConnectionError("redis://person:secret@host/15"))
    monkeypatch.setattr(runtime, "get_settings", lambda: SimpleNamespace(
        redis_url="redis://person:secret@host/15", tryon_queue_name="try-on-demo"
    ))
    monkeypatch.setattr(runtime.Redis, "from_url", lambda *_args, **_kwargs: broker)

    status = runtime.tryon_runtime_status()

    assert status["available"] is False
    assert status["reason"] == "redis_unavailable"
    assert "secret" not in repr(status)
    assert broker.closed


def test_tryon_health_endpoint_returns_runtime_status(client, monkeypatch):
    expected = {
        "status": "unavailable", "available": False, "queue_name": "try-on-demo",
        "components": {"broker": False, "dispatcher": False, "worker": False},
        "reason": "redis_unavailable",
    }
    monkeypatch.setattr(main, "tryon_runtime_status", lambda: expected)

    response = client.get("/health/try-on")

    assert response.status_code == 200
    assert response.json() == expected
