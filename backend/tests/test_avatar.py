import json
import struct
from pathlib import Path
from types import SimpleNamespace

from app.avatars import router as avatars
from app.avatars.glb import AvatarAssetError, validate_avatar_glb
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
    assert client.delete("/avatars/current", headers=bob_headers).status_code == 204

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

    replacement = _save(
        client, headers, consent, asset=_variant(), provider_avatar_id="avaturn-avatar-2",
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["id"] == original["id"]
    assert replacement.json()["version"] == 2
    assert client.get(replacement.json()["model_url"]).content == _variant()
    assert len(list(tmp_path.iterdir())) == 1


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
    assert client.get(avatar["model_url"]).status_code == 200

    removed = client.request(
        "DELETE", "/auth/account", headers=headers, cookies={"dressme_session": cookie},
        json={"password": "correct horse battery staple", "confirmation": "DELETE"},
    )
    assert removed.status_code == 204
    assert client.get("/avatars/current", cookies={"dressme_session": cookie}).status_code == 401
    assert list(tmp_path.iterdir()) == []
