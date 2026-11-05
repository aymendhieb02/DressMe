"""The saved avatar image used as the try-on person photo."""
import io

from PIL import Image

import app.tryon.router as tryon
from app.avatars import router as avatars
from app.storage.local_disk import LocalPrivateStorage
from tests.test_avatar import _consent, _save, _save_render, _variant
from tests.test_tryon import _jpeg, _login, _setup_inputs, _upload_person


def _avatar_with_render(client, headers, monkeypatch, tmp_path):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    consent = _consent(client, headers).json()
    avatar = _save(client, headers, consent)
    assert avatar.status_code == 200, avatar.text
    render = _save_render(client, headers, avatar.json())
    assert render.status_code == 200, render.text
    return consent, avatar.json(), render.json()


def _use_avatar(client, headers, consent=True):
    return client.post("/person-photos/from-avatar", headers=headers, json={"consent": consent})


def test_avatar_image_needs_consent_and_becomes_one_reusable_photo(client, origin, monkeypatch, tmp_path):
    headers, _garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    _avatar_with_render(client, headers, monkeypatch, tmp_path)

    assert client.get("/person-photos/from-avatar").json() is None
    refused = _use_avatar(client, headers, consent=False)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "photo_consent_required"
    assert client.get("/person-photos").json() == []

    created = _use_avatar(client, headers)
    assert created.status_code == 201, created.text
    assert (created.json()["width"], created.json()["height"]) == (576, 768)
    assert client.get("/person-photos/from-avatar").json()["id"] == created.json()["id"]

    again = _use_avatar(client, headers)
    assert again.json()["id"] == created.json()["id"]
    assert len(client.get("/person-photos").json()) == 1
    image = client.get(created.json()["image_url"])
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")


def test_avatar_photo_runs_through_the_normal_job_path(client, origin, monkeypatch, tmp_path):
    headers, garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    _avatar_with_render(client, headers, monkeypatch, tmp_path)
    photo = _use_avatar(client, headers).json()
    job = client.post(
        "/try-on/jobs",
        headers={**headers, "Idempotency-Key": "avatar-job-0001"},
        json={"garment_id": garment["id"], "person_photo_id": photo["id"]},
    )
    assert job.status_code == 202, job.text
    assert job.json()["state"] == "queued"


def test_no_render_means_no_avatar_photo(client, origin, monkeypatch, tmp_path):
    headers, _garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    assert client.get("/person-photos/from-avatar").json() is None
    missing = _use_avatar(client, headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "avatar_render_not_found"


def test_a_new_avatar_version_needs_its_own_consent(client, origin, monkeypatch, tmp_path):
    headers, _garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    consent, _avatar, _render = _avatar_with_render(client, headers, monkeypatch, tmp_path)
    first = _use_avatar(client, headers).json()

    replaced = _save(client, headers, consent, asset=_variant(), provider_avatar_id="avaturn-avatar-2")
    assert replaced.status_code == 200, replaced.text
    assert client.get("/person-photos/from-avatar").json() is None
    different = io.BytesIO()
    Image.new("RGB", (576, 768), (90, 40, 120)).save(different, format="PNG")
    render = _save_render(client, headers, replaced.json(), png=different.getvalue())
    assert render.status_code == 200, render.text
    assert client.get("/person-photos/from-avatar").json() is None
    second = _use_avatar(client, headers).json()
    assert second["id"] != first["id"]
    assert len(client.get("/person-photos").json()) == 2


def test_avatar_photo_respects_the_saved_photo_limit(client, origin, monkeypatch, tmp_path):
    headers, _garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    _avatar_with_render(client, headers, monkeypatch, tmp_path)
    limit = tryon.get_settings().max_person_photos
    for _ in range(limit):
        assert _upload_person(client, headers).status_code == 201
    blocked = _use_avatar(client, headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "person_photo_limit"


def test_avatar_photo_stays_with_its_owner(client, origin, monkeypatch, tmp_path):
    alice, _garment, alice_cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    _avatar_with_render(client, alice, monkeypatch, tmp_path)
    photo = _use_avatar(client, alice).json()

    client.cookies.clear()
    bob = {**origin, "X-CSRF-Token": _login(client, "bob@example.com", origin)}
    assert client.get("/person-photos/from-avatar").json() is None
    assert _use_avatar(client, bob).status_code == 404
    assert client.get(photo["image_url"]).status_code == 404


def test_avatar_photo_routes_need_a_session(client, origin):
    assert client.get("/person-photos/from-avatar").status_code == 401
    assert client.post("/person-photos/from-avatar", headers=origin, json={"consent": True}).status_code in {401, 403}


def _job(client, headers, garment, photo, key):
    return client.post(
        "/try-on/jobs",
        headers={**headers, "Idempotency-Key": key},
        json={"garment_id": garment["id"], "person_photo_id": photo["id"]},
    )


def test_history_shows_the_inputs_and_the_place_in_the_queue(client, origin, monkeypatch, tmp_path):
    headers, garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    for number in range(3):
        assert _job(client, headers, garment, photo, f"queue-order-{number}").status_code == 202

    items = client.get("/try-on/jobs").json()["items"]
    assert sorted(item["queue_position"] for item in items) == [0, 1, 2]
    assert [item["queue_position"] for item in items] == [2, 1, 0]  # newest first, so last in line
    first = items[0]
    assert first["garment_category"] == "shirt"
    assert client.get(first["person_image_url"]).status_code == 200
    assert client.get(first["garment_image_url"]).status_code == 200
    assert "garment_image_key" not in first and "input_snapshot" not in first


def test_several_jobs_can_wait_at_once_up_to_the_limit(client, origin, monkeypatch, tmp_path):
    headers, garment, _cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, headers).json()
    limit = tryon.get_settings().max_outstanding_jobs
    assert limit >= 6
    for number in range(limit):
        assert _job(client, headers, garment, photo, f"queue-limit-{number}").status_code == 202
    blocked = _job(client, headers, garment, photo, "queue-limit-over")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "user_job_limit"


def test_queue_position_counts_other_people_without_showing_them(client, origin, monkeypatch, tmp_path):
    alice, garment, alice_cookie = _setup_inputs(client, origin, monkeypatch, tmp_path)
    photo = _upload_person(client, alice).json()
    assert _job(client, alice, garment, photo, "alice-first-job").status_code == 202

    client.cookies.clear()
    bob = {**origin, "X-CSRF-Token": _login(client, "bob@example.com", origin)}
    uploaded = client.post("/garments/analyze", headers=bob, files={"image": ("g.jpg", _jpeg(), "image/jpeg")})
    bob_garment = client.post("/garments", headers=bob, json={
        "pending_upload_id": uploaded.json()["id"], "category": "shirt", "garment_photo_type": "flat-lay",
    }).json()
    bob_photo = _upload_person(client, bob).json()
    assert _job(client, bob, bob_garment, bob_photo, "bob-second-job").status_code == 202

    items = client.get("/try-on/jobs").json()["items"]
    assert len(items) == 1 and items[0]["queue_position"] == 1
