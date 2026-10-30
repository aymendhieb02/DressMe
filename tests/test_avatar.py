import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from PIL import Image, ImageDraw

from app.avatars import router as avatars
from app.avatars.glb import AvatarAssetError, validate_avatar_glb
from app.avatars.render_profile import expected_camera_radius
from app.models import Avatar, AvatarConsent, AvatarRender, StorageDeletion
from app.storage.cleanup import drain_storage_deletions
from app.storage.local_disk import LocalPrivateStorage


FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_avatar.glb"


def _register(client, origin, email="alice@example.com"):
    response = client.post("/auth/register", headers=origin, json={
        "email": email, "password": "correct horse battery staple",
    })
    assert response.status_code == 201, response.text
    return (
        {**origin, "X-CSRF-Token": response.json()["csrf_token"]},
        response.cookies.get("dressme_session"),
    )


def _consent(client, headers, accepted=True):
    return client.post("/avatars/consents", headers=headers, json={"accepted": accepted})


def _save(client, headers, consent, asset=None, provider_avatar_id="avaturn-avatar-1"):
    return client.put(
        "/avatars/current",
        headers=headers,
        data={
            "provider_avatar_id": provider_avatar_id,
            "consent_id": consent["id"],
            "consent_version": consent["consent_version"],
        },
        files={"model": ("avatar.glb", asset or FIXTURE.read_bytes(), "model/gltf-binary")},
    )


def _render_png(size=(576, 768), *, alpha=False):
    mode = "RGBA" if alpha else "RGB"
    background = (244, 243, 238, 255) if alpha else (244, 243, 238)
    image = Image.new(mode, size, background)
    draw = ImageDraw.Draw(image)
    color = (62, 100, 78, 255) if alpha else (62, 100, 78)
    draw.ellipse((size[0] * 0.38, size[1] * 0.08, size[0] * 0.62, size[1] * 0.28), fill=color)
    draw.rectangle((size[0] * 0.25, size[1] * 0.28, size[0] * 0.75, size[1] * 0.72), fill=color)
    draw.rectangle((size[0] * 0.32, size[1] * 0.72, size[0] * 0.45, size[1] * 0.94), fill=color)
    draw.rectangle((size[0] * 0.55, size[1] * 0.72, size[0] * 0.68, size[1] * 0.94), fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _camera_settings(bounds=None):
    bounds = bounds or {"x": 0.5, "y": 1.7, "z": 0.3}
    return {
        "bounds_m": bounds,
        "azimuth_degrees": 0,
        "polar_degrees": 75,
        "fov_degrees": 30,
        "radius_m": expected_camera_radius(bounds),
    }


def _save_render(client, headers, avatar, png=None, *, camera=None, content_type="image/png"):
    return client.put(
        "/avatars/current/render",
        headers=headers,
        data={
            "source_avatar_id": avatar["id"],
            "source_avatar_version": str(avatar["version"]),
            "source_avatar_sha256": avatar["asset_sha256"],
            "camera_settings_json": json.dumps(camera or _camera_settings()),
        },
        files={"image": ("avatar-render.png", png or _render_png(), content_type)},
    )


def _variant():
    data = bytearray(FIXTURE.read_bytes())
    json_length = struct.unpack_from("<I", data, 12)[0]
    binary_header = 20 + json_length
    binary_length = struct.unpack_from("<I", data, binary_header)[0]
    binary_offset = binary_header + 8
    assert binary_length >= 4
    struct.pack_into("<f", data, binary_offset, -0.25)
    return bytes(data)


def _rewrite_document(asset, mutate):
    data = bytearray(asset)
    declared_length = struct.unpack_from("<I", data, 8)[0]
    assert declared_length == len(data)
    json_length = struct.unpack_from("<I", data, 12)[0]
    json_start, json_end = 20, 20 + json_length
    document = json.loads(data[json_start:json_end].decode("utf-8").rstrip(" \t\r\n\x00"))
    mutate(document)
    json_chunk = json.dumps(document, separators=(",", ":")).encode()
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    binary_chunk = bytes(data[json_end:])
    total = 12 + 8 + len(json_chunk) + len(binary_chunk)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
        + binary_chunk
    )


def test_avatar_consent_private_owner_retrieval_and_delete(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    assert client.get("/avatars/current").status_code == 401

    alice_headers, alice_cookie = _register(client, origin)
    assert client.get("/avatars/current").json() is None
    rejected = _consent(client, alice_headers, accepted=False)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "avatar_consent_required"
    no_csrf = client.post("/avatars/consents", headers=origin, json={"accepted": True})
    assert no_csrf.status_code == 403

    consent_response = _consent(client, alice_headers)
    assert consent_response.status_code == 201, consent_response.text
    consent = consent_response.json()
    assert consent["provider"] == "avaturn"
    assert consent["consent_version"] == "avaturn-photo-processing-v1"
    assert consent["consented_at"]

    saved = _save(client, alice_headers, consent)
    assert saved.status_code == 200, saved.text
    avatar = saved.json()
    assert avatar["provider"] == "avaturn"
    assert avatar["version"] == 1
    assert avatar["asset_size"] == len(FIXTURE.read_bytes())
    assert client.get("/avatars/current").json()["id"] == avatar["id"]
    model = client.get(avatar["model_url"])
    assert model.status_code == 200
    assert model.content == FIXTURE.read_bytes()
    assert model.headers["content-type"].startswith("model/gltf-binary")
    assert model.headers["cache-control"] == "private, no-store"
    assert model.headers["x-content-type-options"] == "nosniff"

    bob_headers, bob_cookie = _register(client, origin, "bob@example.com")
    assert bob_cookie and bob_cookie != alice_cookie
    assert client.get("/avatars/current").json() is None
    denied = client.get(avatar["model_url"])
    assert denied.status_code == 404
    denied_replacement = _save(
        client, bob_headers, consent, provider_avatar_id="attempt-to-replace-alice-avatar",
    )
    assert denied_replacement.status_code == 403
    assert client.delete("/avatars/current", headers=bob_headers).status_code == 204
    assert client.get("/avatars/current", cookies={"dressme_session": alice_cookie}).json()["id"] == avatar["id"]
    assert client.get(avatar["model_url"], cookies={"dressme_session": alice_cookie}).content == FIXTURE.read_bytes()

    # Restore the original authenticated user and prove that deletion still needs CSRF.
    assert client.get("/avatars/current", cookies={"dressme_session": alice_cookie}).json()["id"] == avatar["id"]
    denied_delete = client.delete("/avatars/current", headers=origin, cookies={"dressme_session": alice_cookie})
    assert denied_delete.status_code == 403
    deleted = client.delete("/avatars/current", headers=alice_headers, cookies={"dressme_session": alice_cookie})
    assert deleted.status_code == 204
    assert client.get("/avatars/current", cookies={"dressme_session": alice_cookie}).json() is None
    assert list(tmp_path.iterdir()) == []


def test_failed_replacement_preserves_current_avatar_and_success_retires_old_file(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    headers, _cookie = _register(client, origin)
    consent = _consent(client, headers).json()
    original = _save(client, headers, consent).json()
    original_bytes = client.get(original["model_url"]).content
    assert original["version"] == 1

    duplicate = _save(client, headers, consent).json()
    assert duplicate["id"] == original["id"]
    assert duplicate["version"] == 1
    assert len(list(tmp_path.iterdir())) == 1

    bad = _save(client, headers, consent, asset=b"not a glb", provider_avatar_id="avaturn-avatar-2")
    assert bad.status_code == 422
    current = client.get("/avatars/current").json()
    assert current["id"] == original["id"] and current["version"] == 1
    assert client.get(current["model_url"]).content == original_bytes
    assert len(list(tmp_path.iterdir())) == 1

    asset = FIXTURE.read_bytes()
    with monkeypatch.context() as limited_settings:
        limited_settings.setattr(avatars, "get_settings", lambda: SimpleNamespace(max_avatar_bytes=len(asset) - 1))
        oversized = _save(
            client, headers, consent, asset=asset, provider_avatar_id="avaturn-avatar-oversize",
        )
    assert oversized.status_code == 413
    current = client.get("/avatars/current").json()
    assert current["id"] == original["id"] and current["version"] == 1
    assert client.get(current["model_url"]).content == original_bytes
    assert len(list(tmp_path.iterdir())) == 1

    replacement = _save(
        client, headers, consent, asset=_variant(), provider_avatar_id="avaturn-avatar-2",
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["id"] == original["id"]
    assert replacement.json()["version"] == 2
    assert client.get(replacement.json()["model_url"]).content == _variant()
    assert len(list(tmp_path.iterdir())) == 1


def test_avatar_delete_revokes_access_and_retries_failed_private_file_cleanup(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    headers, cookie = _register(client, origin, "avatar-cleanup@example.com")
    consent = _consent(client, headers).json()
    avatar = _save(client, headers, consent).json()
    assert client.get(avatar["model_url"]).status_code == 200

    def fail_delete(_self, _key):
        raise OSError("temporary storage failure")

    with monkeypatch.context() as failed_storage:
        failed_storage.setattr(LocalPrivateStorage, "delete", fail_delete)
        removed = client.delete("/avatars/current", headers=headers, cookies={"dressme_session": cookie})
    assert removed.status_code == 202
    assert removed.json()["status"] == "deletion_queued"
    assert client.get("/avatars/current", cookies={"dressme_session": cookie}).json() is None
    assert client.get(avatar["model_url"], cookies={"dressme_session": cookie}).status_code == 404
    with client.app.state.testing_session_factory() as db:
        queued = db.scalars(select(StorageDeletion)).all()
        assert len(queued) == 1 and queued[0].attempts == 1
        assert db.scalars(select(Avatar)).all() == []

    removed_files = drain_storage_deletions(
        session_factory=client.app.state.testing_session_factory,
        storage_factory=lambda: LocalPrivateStorage(tmp_path),
    )
    assert removed_files == 1
    assert list(tmp_path.iterdir()) == []
    with client.app.state.testing_session_factory() as db:
        assert db.scalars(select(StorageDeletion)).all() == []


def test_glb_validation_rejects_unsafe_references_corruption_and_oversize(client, origin, monkeypatch):
    asset = FIXTURE.read_bytes()
    headers, _cookie = _register(client, origin)
    consent = _consent(client, headers).json()

    remote_reference = _rewrite_document(asset, lambda doc: doc["buffers"][0].update({"uri": "file:///private/secret.bin"}))
    rejected = _save(client, headers, consent, asset=remote_reference)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "external_avatar_resource"

    wrong_mime = client.put(
        "/avatars/current", headers=headers,
        data={"provider_avatar_id": "avatar-x", "consent_id": consent["id"], "consent_version": consent["consent_version"]},
        files={"model": ("avatar.glb", asset, "text/plain")},
    )
    assert wrong_mime.status_code == 415

    monkeypatch.setattr(avatars, "get_settings", lambda: SimpleNamespace(max_avatar_bytes=len(asset) - 1))
    too_large = _save(client, headers, consent, asset=asset)
    assert too_large.status_code == 413
    try:
        validate_avatar_glb(asset[:-1], len(asset))
    except AvatarAssetError as error:
        assert error.code == "invalid_avatar_glb"
    else:
        raise AssertionError("truncated GLB was accepted")


def test_account_deletion_removes_avatar_file_and_metadata(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    monkeypatch.setattr("app.auth.router.LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    headers, cookie = _register(client, origin)
    consent = _consent(client, headers).json()
    avatar = _save(client, headers, consent).json()
    render = _save_render(client, headers, avatar).json()
    assert client.get(avatar["model_url"]).status_code == 200

    removed = client.request(
        "DELETE", "/auth/account", headers=headers, cookies={"dressme_session": cookie},
        json={"password": "correct horse battery staple", "confirmation": "DELETE"},
    )
    assert removed.status_code == 204
    assert client.get("/avatars/current", cookies={"dressme_session": cookie}).status_code == 401
    assert list(tmp_path.iterdir()) == []
    with client.app.state.testing_session_factory() as db:
        assert db.scalars(select(Avatar)).all() == []
        assert db.scalars(select(AvatarConsent)).all() == []
        assert db.scalars(select(AvatarRender)).all() == []
    assert client.get(render["image_url"], cookies={"dressme_session": cookie}).status_code == 401


def test_private_avatar_render_is_validated_owner_scoped_and_deletable_without_touching_source(
    client, origin, monkeypatch, tmp_path,
):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    alice_headers, alice_cookie = _register(client, origin, "render-owner@example.com")
    consent = _consent(client, alice_headers).json()
    avatar = _save(client, alice_headers, consent).json()
    original_glb = client.get(avatar["model_url"]).content
    original_hash = hashlib.sha256(original_glb).hexdigest()

    assert client.get("/avatars/current/render", cookies={"dressme_session": "invalid"}).status_code == 401
    assert client.get("/avatars/current/render/export", cookies={"dressme_session": "invalid"}).status_code == 401
    wrong_type = _save_render(client, alice_headers, avatar, content_type="text/plain")
    assert wrong_type.status_code == 415
    wrong_dimensions = _save_render(client, alice_headers, avatar, png=_render_png((320, 320)))
    assert wrong_dimensions.status_code == 422
    opaque_rgba = _save_render(client, alice_headers, avatar, png=_render_png(alpha=True))
    assert opaque_rgba.status_code == 200
    first_render = opaque_rgba.json()
    assert client.get(first_render["image_url"]).status_code == 200
    replacement_render = _save_render(client, alice_headers, avatar)
    assert replacement_render.status_code == 200
    render = replacement_render.json()
    assert client.get(first_render["image_url"]).status_code == 404
    assert render["source_avatar_version"] == avatar["version"]
    assert render["source_avatar_sha256"] == original_hash
    assert render["profile_id"] == "fashn-full-body-frontal"
    assert render["width"] == 576 and render["height"] == 768
    assert render["renderer_version"] == "google-model-viewer@4.3.1"
    assert render["render_settings"]["output"]["width"] == 576
    assert render["render_settings"]["camera"]["framing"] == "bounding-sphere-margin-v1"
    assert "email" not in json.dumps(render).lower()

    image = client.get(render["image_url"])
    assert image.status_code == 200
    assert image.content == _render_png()
    assert image.headers["content-type"].startswith("image/png")
    assert image.headers["cache-control"] == "private, no-store"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert hashlib.sha256(client.get(avatar["model_url"]).content).hexdigest() == original_hash

    export = client.get("/avatars/current/render/export", cookies={"dressme_session": alice_cookie})
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    assert export.headers["cache-control"] == "private, no-store"
    assert export.headers["x-content-type-options"] == "nosniff"
    assert export.headers["content-disposition"].startswith('attachment; filename="dressme-avatar-render-')
    with zipfile.ZipFile(io.BytesIO(export.content)) as bundle:
        assert set(bundle.namelist()) == {"avatar-render.png", "manifest.json"}
        assert bundle.read("avatar-render.png") == _render_png()
        manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["schema"] == "dressme-avatar-render-manifest-v1"
    assert manifest["render"]["id"] == render["id"]
    assert manifest["render"]["sha256"] == render["image_sha256"]
    assert manifest["source_avatar"] == {
        "id": avatar["id"], "version": avatar["version"], "sha256": original_hash,
    }
    assert manifest["settings"] == render["render_settings"]
    assert "email" not in json.dumps(manifest).lower()

    _bob_headers, bob_cookie = _register(client, origin, "render-other@example.com")
    assert client.get(render["image_url"], cookies={"dressme_session": bob_cookie}).status_code == 404
    assert client.get("/avatars/current/render", cookies={"dressme_session": bob_cookie}).json() is None
    assert client.get("/avatars/current/render/export", cookies={"dressme_session": bob_cookie}).status_code == 404
    assert client.delete("/avatars/current/render", headers=origin, cookies={"dressme_session": bob_cookie}).status_code == 403
    assert client.get(render["image_url"], cookies={"dressme_session": alice_cookie}).status_code == 200

    removed = client.delete("/avatars/current/render", headers=alice_headers, cookies={"dressme_session": alice_cookie})
    assert removed.status_code == 204
    assert client.get("/avatars/current/render", cookies={"dressme_session": alice_cookie}).json() is None
    assert client.get(render["image_url"], cookies={"dressme_session": alice_cookie}).status_code == 404
    assert client.get(avatar["model_url"], cookies={"dressme_session": alice_cookie}).content == original_glb
    assert len(list(tmp_path.iterdir())) == 1


def test_stale_avatar_render_is_rejected_and_replacement_or_avatar_delete_cleans_derived_image(
    client, origin, monkeypatch, tmp_path,
):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    headers, cookie = _register(client, origin, "render-stale@example.com")
    consent = _consent(client, headers).json()
    avatar_v1 = _save(client, headers, consent).json()
    first = _save_render(client, headers, avatar_v1).json()
    assert len(list(tmp_path.iterdir())) == 2

    avatar_v2 = _save(client, headers, consent, asset=_variant(), provider_avatar_id="avaturn-avatar-v2").json()
    assert avatar_v2["version"] == 2
    assert client.get("/avatars/current/render", cookies={"dressme_session": cookie}).json() is None
    assert client.get(first["image_url"], cookies={"dressme_session": cookie}).status_code == 404
    stale = _save_render(client, headers, avatar_v1)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "avatar_render_source_changed"
    assert len(list(tmp_path.iterdir())) == 1

    second = _save_render(client, headers, avatar_v2).json()
    assert client.get(second["image_url"], cookies={"dressme_session": cookie}).status_code == 200
    deleted = client.delete("/avatars/current", headers=headers, cookies={"dressme_session": cookie})
    assert deleted.status_code == 204
    assert client.get(second["image_url"], cookies={"dressme_session": cookie}).status_code == 404
    assert list(tmp_path.iterdir()) == []
    late = _save_render(client, headers, avatar_v2)
    assert late.status_code == 409
    assert list(tmp_path.iterdir()) == []


def test_avatar_render_rejects_corrupt_png_and_profile_camera_tampering(client, origin, monkeypatch, tmp_path):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    headers, _cookie = _register(client, origin, "render-invalid@example.com")
    consent = _consent(client, headers).json()
    avatar = _save(client, headers, consent).json()
    corrupt = _save_render(client, headers, avatar, png=b"not a PNG")
    assert corrupt.status_code == 422
    bad_camera = _camera_settings()
    bad_camera["azimuth_degrees"] = 22
    tampered = _save_render(client, headers, avatar, camera=bad_camera)
    assert tampered.status_code == 422
    assert client.get("/avatars/current/render").json() is None
    assert len(list(tmp_path.iterdir())) == 1


def test_failed_avatar_render_cleanup_revokes_access_then_shared_retry_removes_file(
    client, origin, monkeypatch, tmp_path,
):
    monkeypatch.setattr(avatars, "LocalPrivateStorage", lambda: LocalPrivateStorage(tmp_path))
    headers, cookie = _register(client, origin, "render-cleanup@example.com")
    consent = _consent(client, headers).json()
    avatar = _save(client, headers, consent).json()
    render = _save_render(client, headers, avatar).json()

    def fail_delete(_self, _key):
        raise OSError("temporary storage failure")

    with monkeypatch.context() as failed_storage:
        failed_storage.setattr(LocalPrivateStorage, "delete", fail_delete)
        response = client.delete("/avatars/current/render", headers=headers, cookies={"dressme_session": cookie})
    assert response.status_code == 202
    assert client.get(render["image_url"], cookies={"dressme_session": cookie}).status_code == 404
    with client.app.state.testing_session_factory() as db:
        queued = db.scalars(select(StorageDeletion)).all()
        assert len(queued) == 1 and queued[0].attempts == 1

    removed = drain_storage_deletions(
        session_factory=client.app.state.testing_session_factory,
        storage_factory=lambda: LocalPrivateStorage(tmp_path),
    )
    assert removed == 1
    assert len(list(tmp_path.iterdir())) == 1
