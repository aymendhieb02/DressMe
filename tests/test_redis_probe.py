from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from app.tryon import redis_probe


class FakeRedis:
    def __init__(self, *, error=None, close_error=None):
        self.error = error
        self.close_error = close_error
        self.closed = False

    def ping(self):
        if self.error:
            raise self.error
        return True

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def test_probe_reports_missing_url_without_loading_redis():
    def fail_if_loaded():
        raise AssertionError("Redis should not be imported without a URL")

    result = redis_probe.probe_redis(None, redis_loader=fail_if_loaded)

    assert result == (2, "Redis probe configuration error: REDIS_URL is not set.")


def test_probe_distinguishes_missing_redis_dependency():
    def missing_dependency():
        raise ModuleNotFoundError("redis is unavailable")

    result = redis_probe.probe_redis("redis://user:secret@localhost/15", redis_loader=missing_dependency)

    assert result == (3, "Redis probe dependency missing: redis.")
    assert "secret" not in repr(result)


def test_probe_reports_timeout_without_traceback_or_credentials_and_closes_client():
    client = FakeRedis(error=RedisTimeoutError("redis://user:secret@localhost/15 timed out"))

    result = redis_probe.probe_redis(
        "redis://user:secret@localhost/15",
        redis_loader=lambda: (type("FakeRedisFactory", (), {"from_url": staticmethod(lambda *_a, **_kw: client)}), RedisError),
    )

    assert result == (1, "Redis broker unavailable (TimeoutError).")
    assert "secret" not in repr(result)
    assert client.closed


def test_probe_success_closes_client():
    client = FakeRedis()
    factory = type("FakeRedisFactory", (), {"from_url": staticmethod(lambda *_a, **_kw: client)})

    assert redis_probe.probe_redis("redis://127.0.0.1/15", redis_loader=lambda: (factory, RedisError)) == (
        0,
        "Redis broker: available.",
    )
    assert client.closed


def test_probe_close_failure_is_controlled():
    client = FakeRedis(close_error=RuntimeError("private connection detail"))
    factory = type("FakeRedisFactory", (), {"from_url": staticmethod(lambda *_a, **_kw: client)})

    result = redis_probe.probe_redis("redis://127.0.0.1/15", redis_loader=lambda: (factory, RedisError))

    assert result == (4, "Redis probe failed (RuntimeError).")
    assert "private connection detail" not in repr(result)
    assert client.closed
