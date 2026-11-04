"""Exercise the integrated Taste pages' real catalog, model, auth and persistence."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api
from app.database import Base, get_db
from app.main import app as studio_app


@pytest.fixture
def taste_client(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(api, "SessionLocal", factory)
    api.app.dependency_overrides[get_db] = override_db
    studio_app.dependency_overrides[get_db] = override_db
    client = TestClient(api.app)
    yield client
    client.close()
    api.app.dependency_overrides.clear()
    studio_app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register(client, email):
    origin = {"Origin": "http://localhost:8002"}
    response = client.post("/studio-api/auth/register", headers=origin,
                           json={"email": email, "password": "correct horse battery staple"})
    assert response.status_code == 201, response.text
    return {**origin, "X-CSRF-Token": response.json()["csrf_token"]}


def test_taste_catalog_reactions_profiles_and_account_isolation(taste_client):
    client = taste_client
    assert client.get("/api/reco/state").status_code == 401
    assert client.get("/reco_img/18836.jpg").status_code == 401

    headers = register(client, "taste-one@example.com")
    feed = client.post("/api/reco/feed", headers=headers, json={"gender": "Women"})
    assert feed.status_code == 200, feed.text
    items = feed.json()["items"]
    assert len(items) == 12
    assert all(item["id"] and item["img"] for item in items)
    assert client.get(items[0]["img"]).status_code == 200

    assert client.post("/api/reco/foryou", headers=headers, json={}).json()["need"] == 3
    assert client.post("/api/bubble/recommendations", headers=headers, json={}).json()["need"] == 3
    assert client.post("/api/reco/reaction", json={"item_id": items[0]["id"], "kind": "like"}).status_code == 403
    for item in items[:5]:
        response = client.post("/api/reco/reaction", headers=headers,
                               json={"item_id": item["id"], "kind": "like"})
        assert response.status_code == 200, response.text
    saved = client.post("/api/reco/reaction", headers=headers,
                        json={"item_id": items[5]["id"], "kind": "save"})
    assert saved.status_code == 200
    user_state = client.get("/api/reco/state").json()
    assert len(user_state["liked"]) == 6
    assert user_state["saved"][0]["id"] == items[5]["id"]
    assert client.post("/api/reco/foryou", headers=headers, json={"gender": "Women"}).json()["ready"]
    assert client.post("/api/reco/profile", headers=headers, json={}).json()["ready"]
    bubble = client.post("/api/bubble/recommendations", headers=headers,
                         json={"gender": "Women", "alpha": 0.8})
    assert bubble.status_code == 200, bubble.text
    assert bubble.json()["ready"] and bubble.json()["items"]
    assert bubble.json()["items"][0]["img"].startswith("/reco_img/")
    from_likes = client.post("/api/style/likes", headers=headers, json={"gender": "Women"})
    assert from_likes.status_code == 200, from_likes.text
    assert len(from_likes.json()["items"]) == 6
    assert from_likes.json()["recs"]

    client.cookies.clear()
    other_headers = register(client, "taste-two@example.com")
    assert client.get("/api/reco/state").json()["liked"] == []
    assert client.post("/api/reco/foryou", headers=other_headers, json={}).json()["need"] == 3
    assert client.delete("/api/reco/state", headers=other_headers).status_code == 200


def test_style_model_sample_upload_and_invalid_upload(taste_client):
    client = taste_client
    headers = register(client, "style-one@example.com")
    sample = client.post("/api/style/sample", headers=headers, json={"gender": "Women"})
    assert sample.status_code == 200, sample.text
    result = sample.json()
    assert result["dominant"] in {"Casual", "Sporty", "Formal", "Ethnic"}
    assert len(result["profile"]) == 4
    assert result["items"][0]["img"].startswith("/reco_img/")
    assert result["recs"]

    image_path = Path(api.DATA) / "reco" / "thumbs" / result["items"][0]["img"].rsplit("/", 1)[1]
    uploaded = client.post("/api/style/photos", headers=headers, data={"gender": "Women"},
                           files=[("files", ("sample.jpg", image_path.read_bytes(), "image/jpeg"))])
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["dominant"] in {"Casual", "Sporty", "Formal", "Ethnic"}
    invalid = client.post("/api/style/photos", headers=headers,
                          files=[("files", ("bad.txt", b"not a photo", "text/plain"))])
    assert invalid.status_code == 400
