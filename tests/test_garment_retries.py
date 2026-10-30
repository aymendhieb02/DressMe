import io
from uuid import uuid4

from PIL import Image
from sqlalchemy import func, select

from app.garments import router
from app.ml.client import BO6AnalyzeResponse, BO6Unavailable
from app.models import Garment, PendingUpload
from app.storage.local_disk import LocalPrivateStorage
from tests.test_garments import _jpeg, _login, _prediction


def test_explicit_upload_and_save_retries_recover_without_extra_rows_or_files(client, origin, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(router, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))

    async def analyze(*_):
        calls.append(1)
        if len(calls) == 1:
            raise BO6Unavailable("fixture outage")
        return BO6AnalyzeResponse(quality={"version": "quality-v0.1"}, prediction=_prediction())

    monkeypatch.setattr(router.BO6Client, "analyze", analyze)
    key = str(uuid4())
    headers = {**origin, "X-CSRF-Token": _login(client, "retry-owner@example.invalid", origin), "Idempotency-Key": key}
    def upload(content=None):
        return client.post("/garments/analyze", headers=headers, files={"image": ("photo.jpg", content or _jpeg(), "image/jpeg")})
    assert upload().status_code == 503
    assert list(tmp_path.iterdir()) == []
    first, replay = upload(), upload()
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"] == key
    assert len(calls) == 2 and len(list(tmp_path.iterdir())) == 1
    stream = io.BytesIO()
    Image.new("RGB", (160, 100), "red").save(stream, format="JPEG")
    assert upload(stream.getvalue()).status_code == 409
    payload = {"pending_upload_id": key, "category": "shirt", "garment_photo_type": "flat-lay", "description": "My confirmed wording"}
    saved = client.post("/garments", headers=headers, json=payload)
    replay = client.post("/garments", headers=headers, json=payload)
    assert saved.status_code == replay.status_code == 201
    assert saved.json()["id"] == replay.json()["id"]
    assert client.post("/garments", headers=headers, json={**payload, "description": "Different wording"}).status_code == 409
    with client.app.state.testing_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PendingUpload)) == 1
        assert db.scalar(select(func.count()).select_from(Garment)) == 1
    assert len(list(tmp_path.iterdir())) == 1
    client.cookies.clear()
    headers["X-CSRF-Token"] = _login(client, "retry-other@example.invalid", origin)
    assert upload().status_code == 409
    assert client.post("/garments", headers=headers, json=payload).status_code == 404
    assert client.get(saved.json()["image_url"]).status_code == 404
