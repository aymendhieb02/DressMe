import uuid
from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app.models import TryOnAttempt, TryOnJob
from app.storage.local_disk import LocalPrivateStorage
from app.tryon import worker
from app.tryon.worker_tasks import process_mock_job
from tests.test_tryon import _login, _setup_inputs, _upload_person


@pytest.mark.parametrize("mode,settings", [
    ("real", {"mode": "mock", "adapter": "mock-preview-v1"}),
    ("mock", {"mode": "real", "adapter": "mock-preview-v1"}),
    ("mock", {"mode": "mock", "adapter": "fashn-vton-1.5"}),
    ("mock", {}),
])
def test_stale_delivery_cannot_substitute_mock_for_an_unsupported_profile(
    client, origin, monkeypatch, tmp_path, mode, settings
):
    headers, garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    submitted = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": "stale-delivery-01"}, json={
        "garment_id": garment["id"], "person_photo_id": photo["id"]
    }).json()
    factory = client.app.state.testing_session_factory
    with factory() as db:
        job = db.get(TryOnJob, uuid.UUID(submitted["id"]))
        job.mode, job.settings_snapshot = mode, settings
        db.commit()
    before = set(tmp_path.iterdir())

    class UnavailableStorage:
        def read(self, _key):
            raise AssertionError("unsupported adapters must not read private inputs")

        def put(self, _content):
            raise AssertionError("unsupported adapters must not write a mock result")

    process_mock_job(submitted["id"], factory, UnavailableStorage())
    completed = client.get(submitted["status_url"]).json()
    assert completed["state"] == "failed"
    assert completed["error_code"] == "unsupported_vton_adapter"
    assert completed["result_url"] is None and completed["result_metadata"] is None
    assert client.get(f"{submitted['status_url']}/result").status_code == 404
    assert set(tmp_path.iterdir()) == before
    with factory() as db:
        job = db.get(TryOnJob, uuid.UUID(submitted["id"]))
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.job_id == job.id))
        assert job.active_attempt_token is None
        assert attempt.state == "failed" and attempt.error_code == "unsupported_vton_adapter"


@pytest.mark.parametrize("platform,simple_mock", [("nt", True), ("posix", False)])
def test_worker_uses_json_queue_and_honors_bounded_launch(monkeypatch, capsys, platform, simple_mock):
    calls = []

    class Broker:
        def ping(self):
            calls.append("ping")

        def close(self):
            calls.append("close")

    broker = Broker()
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(
        vton_mode="mock", environment="development", redis_url="redis://localhost:6379/15"
    ))
    monkeypatch.setattr(worker.Redis, "from_url", lambda *_args, **_kwargs: broker)

    class CapturingQueue:
        def __init__(self, name, **kwargs):
            assert name == "try-on"
            assert kwargs["connection"] is broker
            assert kwargs["serializer"] is worker.JSONSerializer

    class CapturingWorker:
        def __init__(self, queues, **kwargs):
            assert len(queues) == 1
            assert kwargs["connection"] is broker
            assert kwargs["serializer"] is worker.JSONSerializer

        def work(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(worker, "Queue", CapturingQueue)
    selected = "SimpleWorker" if simple_mock else "Worker"
    other = "Worker" if simple_mock else "SimpleWorker"
    monkeypatch.setattr(worker, selected, CapturingWorker)
    monkeypatch.setattr(worker, other, lambda *_args, **_kwargs: pytest.fail("wrong worker isolation mode"))
    monkeypatch.setattr(worker, "os", SimpleNamespace(name=platform))
    args = (["--simple-mock"] if simple_mock else []) + ["--burst", "--max-jobs", "1"]
    assert worker.main(args) == 0
    assert calls == ["ping", {"burst": True, "max_jobs": 1}, "close"]
    assert ("MOCK ONLY" in capsys.readouterr().err) == simple_mock


@pytest.mark.parametrize("mode,environment,simple_mock,message", [
    ("real", "development", True, "no mock result was substituted"),
    ("mock", "production", True, "restricted to development/test"),
    ("mock", "development", False, "requires Linux/Compose"),
])
def test_unsupported_worker_launch_fails_before_broker_access(monkeypatch, mode, environment, simple_mock, message):
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(vton_mode=mode, environment=environment))
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(worker.Redis, "from_url", lambda *_args, **_kwargs: pytest.fail("must fail before broker access"))
    with pytest.raises(RuntimeError, match=message):
        worker.run_worker(simple_mock=simple_mock)


def test_broker_startup_failure_has_a_clear_exit_and_closes_client(monkeypatch, capsys):
    closed = []

    class Broker:
        def ping(self):
            raise RedisConnectionError("unavailable")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(
        vton_mode="mock", environment="development", redis_url="redis://localhost:6379/15"
    ))
    monkeypatch.setattr(worker.Redis, "from_url", lambda *_args, **_kwargs: Broker())
    assert worker.main(["--simple-mock", "--burst"]) == 1
    assert closed == [True]
    assert "Redis is unavailable" in capsys.readouterr().err


def test_worker_cli_rejects_an_unbounded_invalid_job_limit():
    with pytest.raises(SystemExit) as error:
        worker.main(["--max-jobs", "0"])
    assert error.value.code == 2


def test_completed_mock_result_is_retrievable_only_by_its_owner(client, origin, monkeypatch, tmp_path):
    headers, garment, alice_cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    submitted = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": "private-result-01"}, json={
        "garment_id": garment["id"], "person_photo_id": photo["id"]
    }).json()
    process_mock_job(submitted["id"], client.app.state.testing_session_factory, LocalPrivateStorage(tmp_path))
    completed = client.get(submitted["status_url"]).json()
    assert completed["state"] == "succeeded"
    assert completed["result_metadata"]["mode"] == "mock"
    assert completed["result_metadata"]["adapter"] == "mock-preview-v1"
    result_url = completed["result_url"]
    result = client.get(result_url)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.content.startswith(b"\x89PNG\r\n\x1a\n")
    client.cookies.clear()
    assert client.get(result_url).status_code == 401
    _login(client, "bob@example.com", origin)
    assert client.get(result_url).status_code == 404
    client.cookies.clear()
    client.cookies.set("dressme_session", alice_cookie)
    assert client.get(result_url).content == result.content
