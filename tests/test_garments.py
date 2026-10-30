import io

from PIL import Image

from app.garments import router as garments
from app.ml.client import BO6AnalyzeResponse, BO6DescribeResponse
from app.storage.local_disk import LocalPrivateStorage
from app.storage.cleanup import drain_storage_deletions
from app.models import StorageDeletion
from sqlalchemy import select


def _jpeg():
    stream = io.BytesIO()
    Image.new("RGB", (160, 100), (20, 80, 180)).save(stream, format="JPEG")
    return stream.getvalue()


def _prediction():
    return {
        "category": "shirt", "score": 0.8, "score_type": "uncalibrated_softmax",
        "suggestions": [{"category": "shirt", "score": 0.8}],
        "description": "A garment.",
        "description_fields": {"category": "unknown", "color": "unknown", "pattern": "unknown", "sleeve_length": "unknown"},
        "description_provenance": {"category": "withheld_low_score", "color": "not_estimated", "pattern": "not_estimated", "sleeve_length": "not_estimated"},
        "description_version": "tmpl-v0.4-attributes", "model_version": "E03_efficientnet_b0",
        "taxonomy_version": "dressme-v0.2", "attributes": {},
    }


def _login(client, email, origin):
    response = client.post("/auth/register", headers=origin,
                          json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201
    return response.json()["csrf_token"]


def test_real_contract_upload_review_save_edit_and_private_delete(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(garments, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))

    async def analyze(_self, _content, _filename, _content_type):
        return BO6AnalyzeResponse(quality={
            "version": "quality-v0.1", "advisory_only": True,
            "warnings": [{"code": "blurry", "message": "The photo may be blurry.", "action": "Retake in focus."}],
        }, prediction=_prediction())

    async def describe(_self, confirmed):
        color = confirmed.get("color")
        return BO6DescribeResponse(text=f"A {color + ' ' if color else ''}{confirmed['category']}.",
                                   fields=confirmed, provenance={key: "user_confirmed" for key in confirmed},
                                   schema_version="tmpl-v0.4-attributes")

    monkeypatch.setattr("app.garments.router.BO6Client.analyze", analyze)
    monkeypatch.setattr("app.garments.router.BO6Client.describe", describe)
    csrf = _login(client, "alice@example.com", origin)
    headers = {**origin, "X-CSRF-Token": csrf}

    uploaded = client.post("/garments/analyze", headers=headers,
                           files={"image": ("shirt.jpg", _jpeg(), "image/jpeg")})
    assert uploaded.status_code == 201, uploaded.text
    pending = uploaded.json()
    assert pending["prediction"]["score_type"] == "uncalibrated_softmax"
    assert pending["quality"]["warnings"] == [{
        "code": "blurry", "message": "The photo may be blurry.", "action": "Retake in focus.",
    }]
    assert pending["quality"]["advisory_only"] is True
    assert client.get(pending["image_url"]).status_code == 200

    reviewed = client.post("/garments", headers=headers, json={
        "pending_upload_id": pending["id"], "category": "shirt", "color": "blue", "garment_photo_type": "flat-lay"
    })
    assert reviewed.status_code == 201, reviewed.text
    garment = reviewed.json()
    assert garment["description"] == "A blue shirt."
    assert garment["field_sources"]["color"] == "user_confirmed"
    assert garment["prediction_snapshot"]["score_type"] == "uncalibrated_softmax"
    assert garment["quality_snapshot"]["warnings"] == pending["quality"]["warnings"]
    assert garment["garment_photo_type"] == "flat-lay"
    assert garment["vton_eligibility"] == {
        "status": "disabled", "eligible": False, "candidate_category": "tops",
        "reason": "mapping_not_visually_validated", "policy_version": "bo6-fashn-candidate-v1",
    }

    edited = client.patch(f"/garments/{garment['id']}", headers=headers, json={"color": "red"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["description"] == "A red shirt."
    assert edited.json()["was_corrected"]["color"] is True
    retyped = client.patch(f"/garments/{garment['id']}", headers=headers, json={"garment_photo_type": "model"})
    assert retyped.status_code == 200 and retyped.json()["garment_photo_type"] == "model"
    assert retyped.json()["field_sources"]["garment_photo_type"] == "user_confirmed"
    cleared = client.patch(f"/garments/{garment['id']}", headers=headers, json={"color": None})
    assert cleared.status_code == 200
    assert cleared.json()["field_sources"]["color"] == "not_estimated"
    assert client.patch(f"/garments/{garment['id']}", headers=headers, json={"category": None}).status_code == 422
    manual = client.patch(f"/garments/{garment['id']}", headers=headers, json={"description": "My favorite shirt"})
    assert manual.status_code == 200 and manual.json()["description_is_manual"] is True
    metadata = client.patch(f"/garments/{garment['id']}", headers=headers, json={"notes": "cotton"})
    assert metadata.status_code == 200 and metadata.json()["description"] == "My favorite shirt"

    assert client.get("/garments?category=shirt").json()["total"] == 1
    assert client.get(f"/garments/{garment['id']}/image").status_code == 200
    assert client.delete(f"/garments/{garment['id']}", headers=headers).status_code == 204
    assert client.get(f"/garments/{garment['id']}").status_code == 404
    assert list(tmp_path.iterdir()) == []


def test_upload_rejects_invalid_image_and_requires_csrf(client, origin):
    csrf = _login(client, "bob@example.com", origin)
    no_csrf = client.post("/garments/analyze", headers=origin,
                          files={"image": ("broken.jpg", b"not an image", "image/jpeg")})
    assert no_csrf.status_code == 403
    response = client.post("/garments/analyze", headers={**origin, "X-CSRF-Token": csrf},
                           files={"image": ("broken.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 422


def test_category_correction_drops_stale_sleeves_but_keeps_manual_text(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(garments, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    fields_seen = []

    async def analyze(_self, _content, _filename, _content_type):
        return BO6AnalyzeResponse(quality={"version": "quality-v0.1"}, prediction=_prediction())

    async def describe(_self, confirmed):
        fields_seen.append(confirmed)
        return BO6DescribeResponse(text=f"A {confirmed['category']}.", fields=confirmed,
                                   provenance={key: "user_confirmed" for key in confirmed}, schema_version="tmpl-v0.4-attributes")

    monkeypatch.setattr("app.garments.router.BO6Client.analyze", analyze)
    monkeypatch.setattr("app.garments.router.BO6Client.describe", describe)
    headers = {**origin, "X-CSRF-Token": _login(client, "sleeves@example.invalid", origin)}
    pending = client.post("/garments/analyze", headers=headers, files={"image": ("shirt.jpg", _jpeg(), "image/jpeg")}).json()
    preview = client.post("/garments/describe", headers=headers, json={"pending_upload_id": pending["id"], "confirmed": {"category": "jeans", "sleeve_length": "long"}})
    assert preview.status_code == 200 and fields_seen[-1] == {"category": "jeans"}
    garment = client.post("/garments", headers=headers, json={"pending_upload_id": pending["id"], "category": "shirt", "sleeve_length": "long", "garment_photo_type": "flat-lay"}).json()
    corrected = client.patch(f"/garments/{garment['id']}", headers=headers, json={"category": "trousers"})
    assert corrected.status_code == 200
    assert corrected.json()["sleeve_length"] is None and corrected.json()["field_sources"]["sleeve_length"] == "not_estimated"
    assert fields_seen[-1] == {"category": "trousers"}
    dress = client.patch(f"/garments/{garment['id']}", headers=headers, json={"category": "dress", "sleeve_length": "long", "description": "My own dress description"})
    assert dress.json()["sleeve_length"] == "long"
    corrected_manual = client.patch(f"/garments/{garment['id']}", headers=headers, json={"category": "jeans"}).json()
    assert corrected_manual["description"] == "My own dress description" and corrected_manual["description_is_manual"] is True
    assert corrected_manual["sleeve_length"] is None


def test_pending_upload_and_garment_are_owner_scoped(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(garments, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))

    async def analyze(_self, _content, _filename, _content_type):
        return BO6AnalyzeResponse(quality={"version": "quality-v0.1"}, prediction=_prediction())

    async def describe(_self, confirmed):
        return BO6DescribeResponse(text=f"A {confirmed['category']}.", fields=confirmed,
                                   provenance={key: "user_confirmed" for key in confirmed}, schema_version="tmpl-v0.4-attributes")

    monkeypatch.setattr("app.garments.router.BO6Client.analyze", analyze)
    monkeypatch.setattr("app.garments.router.BO6Client.describe", describe)
    alice_csrf = _login(client, "owner@example.com", origin)
    alice_headers = {**origin, "X-CSRF-Token": alice_csrf}
    pending = client.post("/garments/analyze", headers=alice_headers,
                          files={"image": ("shirt.jpg", _jpeg(), "image/jpeg")}).json()
    garment = client.post("/garments", headers=alice_headers,
                          json={"pending_upload_id": pending["id"], "category": "shirt", "garment_photo_type": "flat-lay"}).json()
    client.cookies.clear()
    bob_csrf = _login(client, "other@example.com", origin)
    assert client.get(pending["image_url"]).status_code == 404
    assert client.get(f"/garments/{garment['id']}").status_code == 404
    assert client.patch(f"/garments/{garment['id']}", headers={**origin, "X-CSRF-Token": bob_csrf},
                        json={"name": "stolen"}).status_code == 404
    assert client.delete(f"/garments/{garment['id']}", headers={**origin, "X-CSRF-Token": bob_csrf}).status_code == 404


def test_pending_upload_deletion_queues_and_retries_private_file_cleanup(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(garments, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))

    async def analyze(_self, _content, _filename, _content_type):
        return BO6AnalyzeResponse(quality={"version": "quality-v0.1"}, prediction=_prediction())

    monkeypatch.setattr("app.garments.router.BO6Client.analyze", analyze)
    csrf = _login(client, "cleanup@example.com", origin)
    headers = {**origin, "X-CSRF-Token": csrf}
    pending = client.post("/garments/analyze", headers=headers,
                          files={"image": ("shirt.jpg", _jpeg(), "image/jpeg")}).json()
    assert list(tmp_path.glob("*.png"))
    original_delete = LocalPrivateStorage.delete

    def fail_delete(_self, _key):
        raise OSError("temporary storage failure")

    monkeypatch.setattr(LocalPrivateStorage, "delete", fail_delete)
    response = client.delete(f"/garments/uploads/{pending['id']}", headers=headers)
    assert response.status_code == 202
    assert response.json()["status"] == "deletion_queued"
    assert client.get(pending["image_url"]).status_code == 404
    with client.app.state.testing_session_factory() as db:
        queued = db.scalars(select(StorageDeletion)).all()
        assert len(queued) == 1 and queued[0].attempts == 1

    monkeypatch.setattr(LocalPrivateStorage, "delete", original_delete)
    removed = drain_storage_deletions(
        session_factory=client.app.state.testing_session_factory,
        storage_factory=lambda: LocalPrivateStorage(tmp_path),
    )
    assert removed == 1
    assert list(tmp_path.iterdir()) == []
