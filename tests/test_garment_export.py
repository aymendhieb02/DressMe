import csv
from datetime import timedelta
from io import StringIO
from uuid import UUID, uuid4

from app.models import Garment, PendingUpload, utcnow


def _register(client, origin, email):
    response = client.post(
        "/auth/register", headers=origin,
        json={"email": email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return {**origin, "X-CSRF-Token": response.json()["csrf_token"]}, UUID(response.json()["user"]["id"])


def _seed_garment(session_factory, user_id, *, description, name=None, notes=None):
    pending_id = uuid4()
    storage_key = f"PRIVATE_STORAGE_KEY_{uuid4().hex}"
    now = utcnow()
    pending = PendingUpload(
        id=pending_id, user_id=user_id, image_key=storage_key, content_type="image/png",
        image_sha256="a" * 64, width=320, height=240, quality_snapshot={"private": "pending-only"},
        prediction_snapshot={"private": "do-not-export"}, model_version="fixture-model",
        taxonomy_version="dressme-v0.2", description_version="fixture-description",
        quality_version="quality-v0.1", expires_at=now + timedelta(hours=1), consumed_at=now,
    )
    garment = Garment(
        user_id=user_id, pending_upload_id=pending_id, image_key=storage_key,
        category="dress", garment_photo_type="flat-lay", color="red", pattern="floral",
        sleeve_length="long", description=description, description_is_manual=True,
        name=name, notes=notes, prediction_snapshot={"private": "do-not-export"},
        quality_snapshot={"private": "do-not-export"}, field_sources={"category": "user_confirmed"},
        was_corrected={}, model_version="fixture-model", taxonomy_version="dressme-v0.2",
        description_version="fixture-description", description_provenance={"source": "user_manual"},
    )
    with session_factory() as db:
        db.add(pending)
        db.flush()
        db.add(garment)
        db.commit()
    return garment.id, storage_key


def _seed_pending_only(session_factory, user_id):
    now = utcnow()
    pending = PendingUpload(
        user_id=user_id, image_key=f"PENDING_ONLY_{uuid4().hex}", content_type="image/png",
        image_sha256="b" * 64, width=320, height=240, quality_snapshot={}, prediction_snapshot={},
        model_version="fixture-model", taxonomy_version="dressme-v0.2", description_version="fixture-description",
        quality_version="quality-v0.1", expires_at=now + timedelta(hours=1), consumed_at=None,
    )
    with session_factory() as db:
        db.add(pending)
        db.commit()
    return pending.id


def test_private_csv_export_includes_full_owned_wardrobe_and_safe_fields(client, origin):
    alice_headers, alice_id = _register(client, origin, "csv-alice@example.com")
    client.cookies.clear()
    bob_headers, bob_id = _register(client, origin, "csv-bob@example.com")
    client.cookies.clear()
    empty_headers, _empty_id = _register(client, origin, "csv-empty@example.com")

    special_description = '=HYPERLINK("https://example.invalid","Robe, d’été")\nsecond line, "quoted"'
    special_name = "  =1+1"
    special_notes = "\t@SUM(1,1), note"
    special_id, special_key = _seed_garment(
        client.app.state.testing_session_factory, alice_id,
        description=special_description, name=special_name, notes=special_notes,
    )
    alice_ids = {str(special_id)}
    for index in range(49):
        garment_id, _ = _seed_garment(
            client.app.state.testing_session_factory, alice_id,
            description=f"Saved garment {index}", name=f"bulk-{index}",
        )
        alice_ids.add(str(garment_id))
    pending_only_id = _seed_pending_only(client.app.state.testing_session_factory, alice_id)
    bob_id, _ = _seed_garment(
        client.app.state.testing_session_factory, bob_id,
        description="other-user-secret-garment",
    )

    client.cookies.clear()
    unauthenticated = client.get("/garments/export.csv")
    assert unauthenticated.status_code == 401

    client.post("/auth/login", headers=origin, json={"email": "csv-alice@example.com", "password": "correct horse battery staple"})
    response = client.get("/garments/export.csv?category=shirt&page=1&page_size=1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="dressme-wardrobe.csv"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-export-row-count"] == "50"

    reader = csv.DictReader(StringIO(response.content.decode("utf-8-sig")))
    records = list(reader)
    assert set(reader.fieldnames or ()) == {
        "garment_id", "category", "garment_photo_type", "color", "pattern", "sleeve_length",
        "description", "description_mode", "name", "notes", "created_at", "updated_at",
    }
    assert len(records) == 50
    assert {record["garment_id"] for record in records} == alice_ids
    assert str(pending_only_id) not in {record["garment_id"] for record in records}
    special = next(record for record in records if record["garment_id"] == str(special_id))
    assert special == {
        "garment_id": str(special_id), "category": "dress", "garment_photo_type": "flat-lay",
        "color": "red", "pattern": "floral", "sleeve_length": "long",
        "description": "'" + special_description, "description_mode": "manual",
        "name": "'" + special_name, "notes": "'" + special_notes,
        "created_at": special["created_at"], "updated_at": special["updated_at"],
    }
    assert special["created_at"] and special["updated_at"]
    for private_value in (special_key, "other-user-secret-garment", "PRIVATE_STORAGE_KEY", "do-not-export", "pending-only", "password", "token", "image_url"):
        assert private_value.encode() not in response.content
    assert bob_id is not None

    client.cookies.clear()
    client.post("/auth/login", headers=origin, json={"email": "csv-bob@example.com", "password": "correct horse battery staple"})
    bob_export = client.get("/garments/export.csv")
    assert bob_export.status_code == 200 and bob_export.headers["x-export-row-count"] == "1"
    bob_records = list(csv.DictReader(StringIO(bob_export.content.decode("utf-8-sig"))))
    assert [row["garment_id"] for row in bob_records] == [str(bob_id)]
    assert "other-user-secret-garment" in bob_records[0]["description"]
    assert not alice_ids.intersection(row["garment_id"] for row in bob_records)

    client.cookies.clear()
    client.post("/auth/login", headers=origin, json={"email": "csv-empty@example.com", "password": "correct horse battery staple"})
    empty_export = client.get("/garments/export.csv")
    assert empty_export.status_code == 200 and empty_export.headers["x-export-row-count"] == "0"
    assert list(csv.DictReader(StringIO(empty_export.content.decode("utf-8-sig")))) == []
