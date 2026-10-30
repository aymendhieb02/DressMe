"""Offline delivery/recovery checks; Redis and the RQ fetch boundary are explicit fakes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from rq.exceptions import NoSuchJobError
from rq.job import JobStatus
from rq.serializers import JSONSerializer
from sqlalchemy import select

from app.models import TryOnAttempt, TryOnJob, TryOnJobOutbox
from app.storage.local_disk import LocalPrivateStorage
from app.tryon import dispatcher
from app.tryon.worker_tasks import _publish, process_mock_job
from tests.test_tryon import _setup_inputs, _upload_person


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


class CapturingQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _create_job(client, origin, monkeypatch, tmp_path):
    headers, garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers)
    assert photo.status_code == 201
    response = client.post(
        "/try-on/jobs",
        headers={**headers, "Idempotency-Key": "dispatcher-offline-request-01"},
        json={"garment_id": garment["id"], "person_photo_id": photo.json()["id"]},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"]), client.app.state.testing_session_factory


@pytest.mark.parametrize("age_seconds, expected_recovered", [(29, 0), (31, 1)])
def test_missing_published_delivery_obeys_recovery_age_in_sqlite(
    client, origin, monkeypatch, tmp_path, age_seconds, expected_recovered
):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    published_at = NOW - timedelta(seconds=age_seconds)
    with factory() as db:
        outbox = db.get(TryOnJobOutbox, job_id)
        outbox.published_at = published_at
        outbox.delivery_number = 1
        db.commit()

    connection = object()
    fetch_calls = []

    def missing_delivery(delivery_id, **kwargs):
        fetch_calls.append((delivery_id, kwargs))
        raise NoSuchJobError(delivery_id)

    monkeypatch.setattr(dispatcher, "utcnow", lambda: NOW)
    monkeypatch.setattr(dispatcher.Job, "fetch", missing_delivery)
    assert dispatcher.reconcile_deliveries(connection, factory) == expected_recovered
    assert fetch_calls == [(f"tryon-{job_id.hex}-0", {
        "connection": connection, "serializer": JSONSerializer,
    })]

    with factory() as db:
        job = db.get(TryOnJob, job_id)
        outbox = db.get(TryOnJobOutbox, job_id)
        assert job.state == "queued"
        assert job.attempt_count == 0
        assert outbox.delivery_number == 1
        if expected_recovered:
            assert outbox.published_at is None
            assert outbox.next_attempt_at.replace(tzinfo=timezone.utc) == NOW
        else:
            assert outbox.published_at.replace(tzinfo=timezone.utc) == published_at

    queue = CapturingQueue()
    assert dispatcher.dispatch_pending(queue, factory) == expected_recovered
    if expected_recovered:
        assert queue.calls[0][1]["job_id"] == f"tryon-{job_id.hex}-1"
        assert queue.calls[0][1]["unique"] is True
    else:
        assert queue.calls == []


def test_expired_running_lease_requeues_and_finishes_old_attempt_in_sqlite(
    client, origin, monkeypatch, tmp_path
):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    token = uuid4()
    started_at = NOW - timedelta(seconds=dispatcher.RUN_LEASE_SECONDS + 1)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        job.state = "running"
        job.attempt_count = 1
        job.active_attempt_token = token
        job.updated_at = started_at
        db.add(TryOnAttempt(
            job_id=job_id, attempt_number=1, attempt_token=token,
            state="running", started_at=started_at,
        ))
        outbox = db.get(TryOnJobOutbox, job_id)
        outbox.published_at = started_at
        outbox.delivery_number = 1
        db.commit()

    fetch_calls = []

    def running_delivery(delivery_id, **_kwargs):
        fetch_calls.append(delivery_id)
        return SimpleNamespace(get_status=lambda refresh=True: JobStatus.STARTED)

    monkeypatch.setattr(dispatcher, "utcnow", lambda: NOW)
    monkeypatch.setattr(dispatcher.Job, "fetch", running_delivery)
    assert dispatcher.reconcile_deliveries(object(), factory) == 1
    assert fetch_calls == [f"tryon-{job_id.hex}-0"]

    with factory() as db:
        job = db.get(TryOnJob, job_id)
        outbox = db.get(TryOnJobOutbox, job_id)
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
        assert job.state == "queued"
        assert job.active_attempt_token is None
        assert job.attempt_count == 1
        assert job.result_key is None
        assert job.updated_at.replace(tzinfo=timezone.utc) == NOW
        assert outbox.published_at is None
        assert outbox.next_attempt_at.replace(tzinfo=timezone.utc) == NOW
        assert attempt is not None
        assert attempt.state == "timed_out"
        assert attempt.error_code == "worker_lost"
        assert attempt.finished_at.replace(tzinfo=timezone.utc) == NOW


def test_successful_publication_wins_over_concurrent_stale_lease_reconciliation(
    client, origin, monkeypatch, tmp_path
):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    token = uuid4()
    started_at = NOW - timedelta(seconds=dispatcher.RUN_LEASE_SECONDS + 1)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        job.state = "running"
        job.attempt_count = 1
        job.active_attempt_token = token
        job.updated_at = started_at
        db.add(TryOnAttempt(
            job_id=job_id, attempt_number=1, attempt_token=token,
            state="running", started_at=started_at,
        ))
        outbox = db.get(TryOnJobOutbox, job_id)
        outbox.published_at = started_at
        outbox.delivery_number = 1
        db.commit()

    # A synthetic database key models publication; no file or Redis result is claimed.
    result_key = "a" * 32 + ".png"
    published = []

    def publish_after_dispatcher_read(_delivery_id, **_kwargs):
        published.append(_publish(job_id, token, result_key, factory))
        return SimpleNamespace(get_status=lambda refresh=True: JobStatus.STARTED)

    monkeypatch.setattr(dispatcher, "utcnow", lambda: NOW)
    monkeypatch.setattr(dispatcher.Job, "fetch", publish_after_dispatcher_read)
    assert dispatcher.reconcile_deliveries(object(), factory) == 0
    assert published == [True]
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
        outbox = db.get(TryOnJobOutbox, job_id)
        assert job.state == "succeeded"
        assert job.result_key == result_key
        assert job.error_code is None
        assert job.active_attempt_token is None
        assert attempt.state == "succeeded"
        assert attempt.error_code is None
        assert attempt.finished_at is not None
        assert outbox.published_at.replace(tzinfo=timezone.utc) == started_at
        assert outbox.delivery_number == 1

    queue = CapturingQueue()
    assert dispatcher.dispatch_pending(queue, factory) == 0
    assert queue.calls == []


def test_completed_mock_wins_over_stale_queued_cancellation_status(
    client, origin, monkeypatch, tmp_path
):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    published_at = NOW - timedelta(seconds=31)
    with factory() as db:
        outbox = db.get(TryOnJobOutbox, job_id)
        outbox.published_at = published_at
        outbox.delivery_number = 1
        db.commit()

    completed_in_hook = []

    def complete_after_dispatcher_read(_delivery_id, **_kwargs):
        process_mock_job(str(job_id), factory, LocalPrivateStorage(tmp_path))
        with factory() as db:
            completed_in_hook.append(db.get(TryOnJob, job_id).state)
        return SimpleNamespace(get_status=lambda refresh=True: JobStatus.CANCELED)

    monkeypatch.setattr(dispatcher, "utcnow", lambda: NOW)
    monkeypatch.setattr(dispatcher.Job, "fetch", complete_after_dispatcher_read)
    assert dispatcher.reconcile_deliveries(object(), factory) == 0
    assert completed_in_hook == ["succeeded"]
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.job_id == job_id))
        outbox = db.get(TryOnJobOutbox, job_id)
        assert job.state == "succeeded"
        assert job.result_key is not None
        assert job.result_metadata["mode"] == "mock"
        assert attempt.state == "succeeded"
        assert attempt.error_code is None
        assert outbox.published_at.replace(tzinfo=timezone.utc) == published_at
        assert outbox.delivery_number == 1

    result = client.get(f"/try-on/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.content.startswith(b"\x89PNG\r\n\x1a\n")
    queue = CapturingQueue()
    assert dispatcher.dispatch_pending(queue, factory) == 0
    assert queue.calls == []


def test_queued_cancellation_preserves_sqlite_server_default_timestamp_behavior(
    client, origin, monkeypatch, tmp_path
):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    with factory() as db:
        # Leave the API-created job.updated_at server default untouched.
        outbox = db.get(TryOnJobOutbox, job_id)
        outbox.published_at = NOW - timedelta(seconds=31)
        outbox.delivery_number = 1
        db.commit()

    monkeypatch.setattr(dispatcher, "utcnow", lambda: NOW)
    monkeypatch.setattr(dispatcher.Job, "fetch", lambda *_args, **_kwargs:
                        SimpleNamespace(get_status=lambda refresh=True: JobStatus.CANCELED))
    assert dispatcher.reconcile_deliveries(object(), factory) == 1
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        outbox = db.get(TryOnJobOutbox, job_id)
        assert job.state == "cancelled"
        assert job.updated_at.replace(tzinfo=timezone.utc) == NOW
        assert job.result_key is None
        assert job.result_metadata is None
        assert job.attempt_count == 0
        assert outbox.published_at is None

    queue = CapturingQueue()
    assert dispatcher.dispatch_pending(queue, factory) == 0
    assert queue.calls == []


@pytest.mark.parametrize("attempt_count,cancellation_requested,expected_state", [
    (1, True, "cancelled"),
    (dispatcher.MAX_ATTEMPTS, False, "timed_out"),
])
def test_expired_running_lease_respects_cancellation_and_attempt_limit(
    client, origin, monkeypatch, tmp_path, attempt_count, cancellation_requested, expected_state
):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    token = uuid4()
    started_at = NOW - timedelta(seconds=dispatcher.RUN_LEASE_SECONDS + 1)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        job.state = "running"
        job.attempt_count = attempt_count
        job.active_attempt_token = token
        job.updated_at = started_at
        if cancellation_requested:
            job.cancellation_requested_at = started_at
        db.add(TryOnAttempt(
            job_id=job_id, attempt_number=attempt_count, attempt_token=token,
            state="running", started_at=started_at,
        ))
        outbox = db.get(TryOnJobOutbox, job_id)
        outbox.published_at = started_at
        outbox.delivery_number = 1
        db.commit()

    monkeypatch.setattr(dispatcher, "utcnow", lambda: NOW)
    monkeypatch.setattr(dispatcher.Job, "fetch", lambda *_args, **_kwargs:
                        SimpleNamespace(get_status=lambda refresh=True: JobStatus.STARTED))
    assert dispatcher.reconcile_deliveries(object(), factory) == 0
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        attempt = db.scalar(select(TryOnAttempt).where(TryOnAttempt.attempt_token == token))
        assert job.state == expected_state
        assert job.active_attempt_token is None
        assert job.result_key is None
        assert job.error_code == ("worker_lost" if expected_state == "timed_out" else None)
        assert attempt.state == "timed_out"
        assert attempt.error_code == "worker_lost"
        assert attempt.finished_at.replace(tzinfo=timezone.utc) == NOW

    queue = CapturingQueue()
    assert dispatcher.dispatch_pending(queue, factory) == 0
    assert queue.calls == []


@pytest.mark.parametrize("mode, settings", [
    ("real", {"mode": "mock", "adapter": "mock-preview-v1"}),
    ("mock", {"mode": "real", "adapter": "mock-preview-v1"}),
    ("mock", {"mode": "mock", "adapter": "unsupported-adapter"}),
    ("mock", {"mode": "mock"}),
])
def test_unsupported_persisted_profile_fails_without_mock_dispatch(
    client, origin, monkeypatch, tmp_path, mode, settings
):
    job_id, factory = _create_job(client, origin, monkeypatch, tmp_path)
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        job.mode = mode
        job.settings_snapshot = settings
        db.commit()

    queue = CapturingQueue()
    assert dispatcher.dispatch_pending(queue, factory) == 0
    assert queue.calls == []
    with factory() as db:
        job = db.get(TryOnJob, job_id)
        outbox = db.get(TryOnJobOutbox, job_id)
        assert job.state == "failed"
        assert job.error_code == "unsupported_vton_adapter"
        assert job.mode == mode
        assert job.settings_snapshot == settings
        assert job.attempt_count == 0
        assert job.result_key is None
        assert job.result_metadata is None
        assert outbox.published_at is None

    # An unsupported request is terminal; another dispatcher pass must not deliver it.
    assert dispatcher.dispatch_pending(queue, factory) == 0
    assert queue.calls == []


@pytest.mark.parametrize("lease_owned,expected", [(True, True), (False, False)])
def test_dispatcher_heartbeat_is_published_only_while_lease_is_owned(lease_owned, expected):
    class Redis:
        call = None

        def eval(self, script, number_of_keys, *arguments):
            self.call = (script, number_of_keys, arguments)
            return int(lease_owned)

    redis = Redis()
    assert dispatcher._refresh_dispatcher_lease(redis, "try-on-demo", "owner-token") is expected
    script, number_of_keys, arguments = redis.call
    assert "dressme:dispatcher:try-on-demo:lease" in arguments
    assert "dressme:dispatcher:try-on-demo:heartbeat" in arguments
    assert number_of_keys == 2
    assert arguments[2] == "owner-token"
    assert arguments[3] == dispatcher.DISPATCHER_LEASE_SECONDS
    assert "SET" in script and "EXPIRE" in script
