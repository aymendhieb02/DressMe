import io
import uuid

from PIL import Image

from app.auth import router as auth
from app.garments import router as garments
from app.ml.client import BO6AnalyzeResponse, BO6DescribeResponse
from app.storage.local_disk import LocalPrivateStorage
from app.tryon import router as tryon
from app.tryon.dispatcher import dispatch_pending
from app.tryon.worker_tasks import process_mock_job


def _jpeg(color=(20, 80, 180)):
    stream = io.BytesIO()
    Image.new("RGB", (120, 160), color).save(stream, format="JPEG")
    return stream.getvalue()


def _prediction():
    return {
        "category": "shirt", "score_type": "uncalibrated_softmax",
        "suggestions": [{"category": "shirt", "score": 0.8}],
        "description": "A garment.",
        "description_fields": {"category": "unknown", "color": "unknown", "pattern": "unknown", "sleeve_length": "unknown"},
        "description_provenance": {"category": "withheld_low_score"},
        "description_version": "tmpl-v0.4-attributes", "model_version": "E03_efficientnet_b0",
        "taxonomy_version": "dressme-v0.2", "attributes": {},
    }


def _login(client, email, origin):
    response = client.post("/auth/register", headers=origin,
                           json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["csrf_token"]


def _setup_inputs(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(garments, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    monkeypatch.setattr(tryon, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    monkeypatch.setattr(auth, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))

    async def analyze(_self, _content, _filename, _content_type):
        return BO6AnalyzeResponse(quality={"version": "quality-v0.1", "advisory_only": True}, prediction=_prediction())

    async def describe(_self, confirmed):
        return BO6DescribeResponse(text=f"A {confirmed['category']}.", fields=confirmed,
                                  provenance={key: "user_confirmed" for key in confirmed}, schema_version="tmpl-v0.4-attributes")

    monkeypatch.setattr("app.garments.router.BO6Client.analyze", analyze)
    monkeypatch.setattr("app.garments.router.BO6Client.describe", describe)
    csrf = _login(client, "alice@example.com", origin)
    alice_cookie = client.cookies.get("dressme_session")
    headers = {**origin, "X-CSRF-Token": csrf}
    uploaded = client.post("/garments/analyze", headers=headers,
                           files={"image": ("garment.jpg", _jpeg(), "image/jpeg")})
    assert uploaded.status_code == 201, uploaded.text
    garment = client.post("/garments", headers=headers, json={
        "pending_upload_id": uploaded.json()["id"], "category": "shirt", "garment_photo_type": "flat-lay"
    })
    assert garment.status_code == 201, garment.text
    return headers, garment.json(), alice_cookie


def _upload_person(client, headers):
    return client.post("/person-photos", headers=headers,
                       files={"image": ("person.jpg", _jpeg((180, 80, 40)), "image/jpeg")},
                       data={"consent": "true"})


def test_consent_idempotency_worker_result_and_duplicate_delivery(client, origin, monkeypatch, tmp_path):
    headers, garment, _alice_cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    no_consent = client.post("/person-photos", headers=headers,
                             files={"image": ("person.jpg", _jpeg(), "image/jpeg")}, data={"consent": "false"})
    assert no_consent.status_code == 422
    photo = _upload_person(client, headers)
    assert photo.status_code == 201, photo.text
    assert photo.json()["consent_version"] == "person-photo-use-v1"
    assert client.get(photo.json()["image_url"]).headers["cache-control"] == "private, no-store"

    key = "tryon-request-0001"
    body = {"garment_id": garment["id"], "person_photo_id": photo.json()["id"]}
    submitted = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": key}, json=body)
    assert submitted.status_code == 202, submitted.text
    job = submitted.json()
    assert job["state"] == "queued" and job["mode"] == "mock"
    assert job["settings_snapshot"]["adapter"] == "mock-preview-v1"
    replay = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": key}, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == job["id"] and replay.json()["replayed"] is True
    conflict = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": key}, json={
        "garment_id": str(uuid.uuid4()), "person_photo_id": photo.json()["id"]
    })
    assert conflict.status_code == 409

    class CapturingQueue:
        def __init__(self):
            self.calls = []

        def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    queue = CapturingQueue()
    factory = client.app.state.testing_session_factory
    assert dispatch_pending(queue, factory) == 1
    assert queue.calls[0][0][0] == "app.tryon.worker_tasks.run_mock_job"
    assert queue.calls[0][1]["unique"] is True
    assert dispatch_pending(queue, factory) == 0

    process_mock_job(job["id"], factory, LocalPrivateStorage(tmp_path))
    process_mock_job(job["id"], factory, LocalPrivateStorage(tmp_path))
    completed = client.get(job["status_url"])
    assert completed.status_code == 200 and completed.json()["state"] == "succeeded"
    assert completed.json()["result_metadata"]["mode"] == "mock"
    result = client.get(completed.json()["result_url"])
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(result.content)) as preview:
        assert preview.size == (1000, 680)

    cancelled = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": "tryon-request-0003"}, json=body).json()
    cancellation = client.post(f"{cancelled['status_url']}/cancel", headers=headers)
    assert cancellation.status_code == 200 and cancellation.json()["state"] == "cancelled"
    before = len(list(tmp_path.iterdir()))
    process_mock_job(cancelled["id"], factory, LocalPrivateStorage(tmp_path))
    assert client.get(cancelled["status_url"]).json()["state"] == "cancelled"
    assert len(list(tmp_path.iterdir())) == before

    account = client.request("DELETE", "/auth/account", headers=headers, json={
        "password": "correct horse battery staple", "confirmation": "DELETE"
    })
    assert account.status_code == 204
    assert client.get("/auth/me").status_code == 401
    assert list(tmp_path.iterdir()) == []


def test_real_mode_fails_closed_without_mock_fallback(client, origin, monkeypatch, tmp_path):
    from types import SimpleNamespace

    headers, garment, _alice_cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers)
    assert photo.status_code == 201
    monkeypatch.setattr(tryon, "get_settings", lambda: SimpleNamespace(vton_mode="real"))
    response = client.post(
        "/try-on/jobs",
        headers={**headers, "Idempotency-Key": "real-mode-request-01"},
        json={"garment_id": garment["id"], "person_photo_id": photo.json()["id"]},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "real_vton_unavailable"
    assert "no mock result was substituted" in response.json()["error"]["message"]


def test_cors_allows_tryon_idempotency_header(client, origin):
    response = client.options(
        "/try-on/jobs",
        headers={
            **origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key,x-csrf-token",
        },
    )
    assert response.status_code == 200
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in allowed_headers
    assert "x-csrf-token" in allowed_headers


def test_outbox_retains_dispatch_intent_when_redis_is_unavailable(client, origin, monkeypatch, tmp_path):
    from sqlalchemy import select
    from app.models import TryOnJobOutbox

    headers, garment, _alice_cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    job = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": "tryon-request-0004"}, json={
        "garment_id": garment["id"], "person_photo_id": photo["id"]
    }).json()

    class UnavailableQueue:
        def enqueue(self, *_args, **_kwargs):
            raise ConnectionError("Redis is unavailable")

    factory = client.app.state.testing_session_factory
    assert dispatch_pending(UnavailableQueue(), factory) == 0
    with factory() as db:
        outbox = db.scalar(select(TryOnJobOutbox).where(TryOnJobOutbox.job_id == uuid.UUID(job["id"])))
        assert outbox.published_at is None
        assert outbox.publish_attempts == 1
        assert outbox.last_error_code == "redis_unavailable"


def test_job_and_person_photo_are_owner_scoped_and_photo_deletion_cascades(client, origin, monkeypatch, tmp_path):
    headers, garment, alice_cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    job = client.post("/try-on/jobs", headers={**headers, "Idempotency-Key": "tryon-request-0002"}, json={
        "garment_id": garment["id"], "person_photo_id": photo["id"]
    }).json()

    client.cookies.clear()
    bob_csrf = _login(client, "bob@example.com", origin)
    bob_headers = {**origin, "X-CSRF-Token": bob_csrf}
    assert client.get(photo["image_url"]).status_code == 404
    assert client.get(job["status_url"]).status_code == 404
    assert client.delete(f"/person-photos/{photo['id']}", headers=bob_headers).status_code == 404

    client.cookies.clear()
    client.cookies.set("dressme_session", alice_cookie)
    alice_headers = {**origin, "X-CSRF-Token": headers["X-CSRF-Token"]}
    assert client.delete(f"/person-photos/{photo['id']}", headers=alice_headers).status_code == 204
    assert client.get(photo["image_url"]).status_code == 404
    assert client.get(job["status_url"]).status_code == 404
