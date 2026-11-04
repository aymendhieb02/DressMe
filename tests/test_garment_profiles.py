from typing import get_args
from uuid import UUID

import pytest
from sqlalchemy import select

from app.garments import router as garments
from app.garments.schemas import Category
from app.garments.taxonomy import SUPER_AND_OUTFIT_CATEGORY
from app.ml.client import BO6AnalyzeResponse, BO6DescribeResponse
from app.models import Garment, GarmentWardrobeProfile
from app.storage.local_disk import LocalPrivateStorage
from tests.test_garments import _jpeg, _login, _prediction


@pytest.fixture
def bo6(monkeypatch, tmp_path):
    """Stub BO6 with the G2L field set; records every /describe call."""
    monkeypatch.setattr(garments, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    seen = []

    async def analyze(_self, _content, _filename, _content_type):
        prediction = _prediction()
        prediction["description_fields"].update(season="winter", material="wool")
        return BO6AnalyzeResponse(quality={"version": "quality-v0.2"}, prediction=prediction)

    async def describe(_self, confirmed):
        seen.append(confirmed)
        words = [confirmed.get("material"), confirmed["category"]]
        season = "summer" if confirmed.get("material") == "linen" else "all"
        return BO6DescribeResponse(text="A " + " ".join(w for w in words if w) + ".", fields={**confirmed, "season": season},
                                   provenance={key: "user_confirmed" for key in confirmed}, schema_version="tmpl-g2l-v1.0")

    monkeypatch.setattr("app.garments.router.BO6Client.analyze", analyze)
    monkeypatch.setattr("app.garments.router.BO6Client.describe", describe)
    return seen


def _headers(client, origin, email):
    return {**origin, "X-CSRF-Token": _login(client, email, origin)}


def _save(client, headers, **fields):
    pending = client.post("/garments/analyze", headers=headers, files={"image": ("g.jpg", _jpeg(), "image/jpeg")}).json()
    response = client.post("/garments", headers=headers, json={
        "pending_upload_id": pending["id"], "garment_photo_type": "flat-lay", **fields,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _profile(client, garment_id):
    with client.app.state.testing_session_factory() as db:
        return db.scalar(select(GarmentWardrobeProfile).where(GarmentWardrobeProfile.garment_id == garment_id))


def test_every_category_has_wardrobe_fields():
    assert set(get_args(Category)) == set(SUPER_AND_OUTFIT_CATEGORY)


def test_save_creates_a_profile_from_the_corrected_category(client, origin, bo6):
    # The stub predicts "shirt"; the user's correction decides the team fields.
    garment = _save(client, _headers(client, origin, "a@example.invalid"), category="coat", material="wool")
    profile = _profile(client, UUID(garment["id"]))
    assert (profile.super_category, profile.outfit_cat, profile.material) == ("outerwear", "outer", "wool")
    assert profile.item_code.startswith("w_") and len(profile.item_code) == 34
    assert profile.embedding_status == "pending" and profile.clip_embedding is None
    assert garment["outfit_cat"] == "outer" and garment["item_code"] == profile.item_code
    assert garment["description"] == "A wool coat." and bo6[-1]["material"] == "wool"
    assert garment["field_sources"]["material"] == "user_confirmed"
    assert garment["was_corrected"]["category"] is True and garment["was_corrected"]["material"] is False


def test_season_uses_the_confirmed_value_then_the_description_rule(client, origin, bo6):
    headers = _headers(client, origin, "season@example.invalid")
    assert _save(client, headers, category="shirt", season="winter")["season"] == "winter"
    assert _save(client, headers, category="shirt", material="linen")["season"] == "summer"


def test_manual_description_saves_without_bo6_and_keeps_the_predicted_season(client, origin, bo6):
    garment = _save(client, _headers(client, origin, "manual@example.invalid"), category="top", description="My top.")
    assert bo6 == [] and garment["description"] == "My top." and garment["season"] == "winter"


def test_patch_category_updates_team_fields_and_drops_stale_sleeves(client, origin, bo6):
    headers = _headers(client, origin, "patch@example.invalid")
    garment = _save(client, headers, category="shirt", sleeve_length="long")
    updated = client.patch(f"/garments/{garment['id']}", headers=headers, json={"category": "shoes"})
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (body["super_category"], body["outfit_cat"], body["sleeve_length"]) == ("shoes", "shoes", None)


def test_patch_material_rebuilds_the_description_and_season(client, origin, bo6):
    headers = _headers(client, origin, "material@example.invalid")
    garment = _save(client, headers, category="shirt")
    body = client.patch(f"/garments/{garment['id']}", headers=headers, json={"material": "linen"}).json()
    assert body["material"] == "linen" and body["description"] == "A linen shirt." and body["season"] == "summer"
    assert body["field_sources"]["material"] == "user_confirmed"
    cleared = client.patch(f"/garments/{garment['id']}", headers=headers, json={"material": None}).json()
    assert cleared["material"] is None and cleared["field_sources"]["material"] == "not_estimated"


def test_patch_keeps_a_season_the_user_confirmed(client, origin, bo6):
    headers = _headers(client, origin, "keep@example.invalid")
    garment = _save(client, headers, category="shirt", season="winter")
    body = client.patch(f"/garments/{garment['id']}", headers=headers, json={"material": "linen"}).json()
    assert body["season"] == "winter"


def test_garment_without_a_profile_is_served_and_gains_one_on_edit(client, origin, bo6):
    headers = _headers(client, origin, "old@example.invalid")
    garment = _save(client, headers, category="pants")
    with client.app.state.testing_session_factory() as db:
        db.delete(db.scalar(select(GarmentWardrobeProfile)))
        db.commit()
    assert client.get(f"/garments/{garment['id']}").json()["outfit_cat"] is None
    body = client.patch(f"/garments/{garment['id']}", headers=headers, json={"name": "Old pants"}).json()
    assert body["outfit_cat"] == "bottom" and body["item_code"].startswith("w_")


def test_replay_with_a_different_material_is_a_conflict(client, origin, bo6):
    headers = _headers(client, origin, "replay@example.invalid")
    pending = client.post("/garments/analyze", headers=headers, files={"image": ("g.jpg", _jpeg(), "image/jpeg")}).json()
    body = {"pending_upload_id": pending["id"], "garment_photo_type": "flat-lay", "category": "shirt", "material": "wool"}
    first = client.post("/garments", headers=headers, json=body)
    assert first.status_code == 201
    assert client.post("/garments", headers=headers, json=body).json()["id"] == first.json()["id"]
    assert client.post("/garments", headers=headers, json={**body, "material": "silk"}).status_code == 409


def test_delete_removes_the_profile(client, origin, bo6):
    headers = _headers(client, origin, "delete@example.invalid")
    garment = _save(client, headers, category="bag")
    assert client.delete(f"/garments/{garment['id']}", headers=headers).status_code == 204
    with client.app.state.testing_session_factory() as db:
        assert db.scalar(select(Garment)) is None and db.scalar(select(GarmentWardrobeProfile)) is None


def test_account_deletion_removes_garments_and_profiles(client, origin, bo6, monkeypatch, tmp_path):
    monkeypatch.setattr("app.auth.router.LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    headers = _headers(client, origin, "leaving@example.invalid")
    _save(client, headers, category="bag")
    deleted = client.request("DELETE", "/auth/account", headers=headers, json={
        "password": "correct horse battery staple", "confirmation": "DELETE",
    })
    assert deleted.status_code == 204, deleted.text
    with client.app.state.testing_session_factory() as db:
        assert db.scalar(select(Garment)) is None and db.scalar(select(GarmentWardrobeProfile)) is None


def test_pants_have_exactly_the_try_on_eligibility_of_trousers(client, origin, bo6):
    headers = _headers(client, origin, "alias@example.invalid")
    pants = _save(client, headers, category="pants")["vton_eligibility"]
    trousers = _save(client, headers, category="trousers")["vton_eligibility"]
    assert pants == trousers and pants["candidate_category"] == "bottoms"


def test_other_new_categories_stay_outside_try_on_for_now(client, origin, bo6):
    headers = _headers(client, origin, "vton@example.invalid")
    for category in ("blouse", "cardigan", "jumpsuit", "coat", "shoes"):
        assert _save(client, headers, category=category)["vton_eligibility"]["candidate_category"] is None


def test_choosing_the_top_suggestion_of_a_withheld_category_is_not_a_correction(client, origin, bo6):
    # The stub withholds the category ("unknown") and suggests "shirt" first.
    headers = _headers(client, origin, "honest@example.invalid")
    garment = _save(client, headers, category="shirt")
    assert garment["was_corrected"]["category"] is False
    moved = client.patch(f"/garments/{garment['id']}", headers=headers, json={"category": "coat"}).json()
    assert moved["was_corrected"]["category"] is True
    back = client.patch(f"/garments/{garment['id']}", headers=headers, json={"category": "shirt"}).json()
    assert back["was_corrected"]["category"] is False


def _bo6_down(monkeypatch, tmp_path):
    from app.ml.client import BO6Unavailable
    monkeypatch.setattr(garments, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))

    async def down(*_args):
        raise BO6Unavailable("fixture outage")

    monkeypatch.setattr("app.garments.router.BO6Client.analyze", down)
    monkeypatch.setattr("app.garments.router.BO6Client.describe", down)


def test_manual_upload_saves_a_garment_while_bo6_is_down(client, origin, monkeypatch, tmp_path):
    _bo6_down(monkeypatch, tmp_path)
    headers = _headers(client, origin, "offline@example.invalid")
    files = {"image": ("g.jpg", _jpeg(), "image/jpeg")}
    assert client.post("/garments/analyze", headers=headers, files=files).status_code == 503
    uploaded = client.post("/garments/uploads/manual", headers=headers, files=files)
    assert uploaded.status_code == 201, uploaded.text
    pending = uploaded.json()
    assert pending["prediction"] == {"status": "unavailable", "suggestions": []}
    assert client.get(pending["image_url"]).status_code == 200
    body = {"pending_upload_id": pending["id"], "garment_photo_type": "flat-lay", "category": "coat"}
    assert client.post("/garments", headers=headers, json=body).status_code == 503  # no generated text available
    saved = client.post("/garments", headers=headers, json={**body, "description": "My old coat."})
    assert saved.status_code == 201, saved.text
    garment = saved.json()
    assert garment["description"] == "My old coat." and garment["model_version"] == "manual"
    assert garment["outfit_cat"] == "outer" and garment["was_corrected"]["category"] is True


def test_manual_upload_keeps_the_upload_rules(client, origin, monkeypatch, tmp_path):
    _bo6_down(monkeypatch, tmp_path)
    headers = _headers(client, origin, "rules@example.invalid")
    assert client.post("/garments/uploads/manual", headers=headers,
                       files={"image": ("g.gif", b"GIF89a", "image/gif")}).status_code == 415
    assert client.post("/garments/uploads/manual", headers=headers,
                       files={"image": ("g.jpg", b"not an image", "image/jpeg")}).status_code == 422
    assert client.post("/garments/uploads/manual", headers=origin,
                       files={"image": ("g.jpg", _jpeg(), "image/jpeg")}).status_code == 403


def test_unknown_values_are_still_rejected(client, origin, bo6):
    headers = _headers(client, origin, "reject@example.invalid")
    pending = client.post("/garments/analyze", headers=headers, files={"image": ("g.jpg", _jpeg(), "image/jpeg")}).json()
    base = {"pending_upload_id": pending["id"], "garment_photo_type": "flat-lay", "category": "shirt"}
    for extra in ({"material": "plastic"}, {"season": "monsoon"}, {"category": "hat"}):
        assert client.post("/garments", headers=headers, json={**base, **extra}).status_code == 422


def test_profiles_are_owned_by_the_saving_user(client, origin, bo6):
    alice = _save(client, _headers(client, origin, "alice2@example.invalid"), category="shirt")
    client.cookies.clear()
    _login(client, "bob2@example.invalid", origin)
    assert client.get(f"/garments/{alice['id']}").status_code == 404
    assert client.get("/garments").json()["items"] == []
