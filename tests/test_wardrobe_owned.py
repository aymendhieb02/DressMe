"""The real wardrobe routes on a small fake catalog, with garments in a test database."""
import json
from datetime import timedelta
from uuid import uuid4

import numpy as np
import pytest
import torch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import wardrobe
import wardrobe_owned
from app.models import Garment, GarmentWardrobeProfile, PendingUpload, User, utcnow

CATEGORIES = ["top", "top", "top", "bottom", "bottom", "bottom", "shoes", "shoes", "shoes", "bag", "bag", "dress"]


class FakeScoring:
    def __init__(self, embeddings):
        self._S = {"E": embeddings}
        self.sizes = []

    def score_outfits(self, outfits, E=None):
        matrix = self._S["E"] if E is None else E
        self.sizes.append(len(matrix))
        assert all(i < len(matrix) for outfit in outfits for i in outfit)
        return np.full(len(outfits), 8.0)


class FakeCatalog:
    TEST = []
    COLORS = []

    def __init__(self):
        rng = np.random.default_rng(1)
        vectors = rng.normal(size=(len(CATEGORIES), 512)).astype("float32")
        self.EMB = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        self.CAT = np.asarray(CATEGORIES)
        self.BYCAT = {c: np.flatnonzero(self.CAT == c).tolist() for c in set(CATEGORIES)}
        self.scoring = FakeScoring(torch.tensor(self.EMB))

    def it(self, i):
        return dict(i=int(i), c=str(self.CAT[i]), d=f"item {i}", k=f"P{i:08d}")


@pytest.fixture
def catalog(client, monkeypatch):
    fake = FakeCatalog()
    ids = set(range(len(CATEGORIES)))
    monkeypatch.setattr(wardrobe, "A", lambda: fake)
    monkeypatch.setattr(wardrobe, "gender_ids", lambda: {"women": ids, "men": ids})
    monkeypatch.setattr(wardrobe_owned, "SessionLocal", client.app.state.testing_session_factory)
    monkeypatch.setattr(wardrobe_owned, "enabled", lambda: True)
    wardrobe.auto_thr.cache_clear()
    yield fake
    wardrobe.auto_thr.cache_clear()


@pytest.fixture
def api():
    application = FastAPI()

    @application.middleware("http")
    async def identity(request: Request, call_next):
        user = request.headers.get("x-test-user")
        if user:
            request.state.assistant_identity = {"id": user}
        return await call_next(request)

    application.include_router(wardrobe.router)
    return TestClient(application)


def _user(client) -> User:
    with client.app.state.testing_session_factory() as db:
        user = User(email=f"{uuid4().hex}@example.invalid", password_hash="x")
        db.add(user)
        db.commit()
        return user


def _garment(client, user, outfit_cat="top", category="shirt", vector=True, status=None):
    key = uuid4().hex + ".png"
    with client.app.state.testing_session_factory() as db:
        pending = PendingUpload(
            user_id=user.id, image_key=key, content_type="image/png", image_sha256="a" * 64, width=1, height=1,
            quality_snapshot={}, prediction_snapshot={}, model_version="m", taxonomy_version="t",
            description_version="d", quality_version="q", expires_at=utcnow() + timedelta(hours=1), consumed_at=utcnow(),
        )
        db.add(pending)
        db.flush()
        garment = Garment(
            user_id=user.id, pending_upload_id=pending.id, image_key=key, category=category, description="A real garment.",
            prediction_snapshot={}, quality_snapshot={}, field_sources={}, was_corrected={},
            model_version="m", taxonomy_version="t", description_version="d",
        )
        values = np.full(512, 1 / np.sqrt(512), dtype=np.float32)
        garment.profile = GarmentWardrobeProfile(
            user_id=user.id, item_code="w_" + uuid4().hex, outfit_cat=outfit_cat,
            clip_embedding=values.tobytes() if vector else None,
            embedding_model=wardrobe_owned.EMBEDDING_MODEL if vector else None,
            embedding_status=status or ("ready" if vector else "pending"),
        )
        db.add(garment)
        db.commit()
        return wardrobe_owned.PUBLIC_ID_BASE + garment.profile.seq


def _post(api, path, user=None, **body):
    headers = {"x-test-user": str(user.id)} if user else {}
    return api.post("/api/wardrobe/" + path, json=body, headers=headers)


ITEMS = [0, 3, 6]


def test_flag_off_gives_identical_bytes_and_never_reads_garments(client, catalog, api, monkeypatch):
    user = _user(client)
    _garment(client, user)
    baseline = {path: _post(api, path, items=ITEMS, gender="women").content for path in ("analyze", "complete", "outfits")}
    monkeypatch.setattr(wardrobe_owned, "enabled", lambda: False)
    monkeypatch.setattr(wardrobe_owned, "load_owned", lambda *a, **k: pytest.fail("flag off must not read garments"))
    for path, expected in baseline.items():
        assert _post(api, path, user, items=ITEMS, gender="women").content == expected


def test_user_without_garments_gets_identical_bytes(client, catalog, api):
    user = _user(client)
    for path in ("analyze", "complete", "outfits"):
        anonymous = _post(api, path, items=ITEMS, gender="women")
        assert _post(api, path, user, items=ITEMS, gender="women").content == anonymous.content
        assert b"owned" not in anonymous.content


def test_owned_pieces_appear_in_looks_and_are_marked(client, catalog, api):
    user = _user(client)
    public_id = _garment(client, user)
    body = _post(api, "complete", user, items=ITEMS, gender="women", n=1).json()
    assert any(public_id in look["owned"] for look in body["looks"])
    item = next(i for look in body["looks"] for i in look["items"] if i["i"] == public_id)
    assert item["owned"] is True and item["k"].startswith("w_") and "/studio-api/garments/" in item["photo"]
    assert item["d"] == "A real garment"
    assert body["owned_in_looks"][0]["i"] == public_id and body["owned_in_looks"][0]["looks"] >= 1


def test_at_most_four_of_six_looks_contain_owned_pieces(client, catalog, api):
    user = _user(client)
    _garment(client, user)
    _garment(client, user, outfit_cat="shoes", category="shoes")
    body = _post(api, "complete", user, items=[0, 1, 2, 3, 4, 5, 6, 7, 8], gender="women", n=1, full_look=False).json()
    looks = body["looks"]
    assert len(looks) == 6
    assert sum(bool(look["owned"]) for look in looks) == 4
    plain = [look for look in looks if not look["owned"]]
    assert len(plain) == 2 and all(item["i"] < len(CATEGORIES) for look in plain for item in look["items"])


def test_looks_fall_back_when_only_owned_outfits_exist(client, catalog, api):
    user = _user(client)
    top = _garment(client, user)
    bottom = _garment(client, user, outfit_cat="bottom", category="jeans")
    shoes = _garment(client, user, outfit_cat="shoes", category="shoes")
    looks = _post(api, "outfits", user, items=[], gender="women", k=3).json()["looks"]
    assert looks and all({top, bottom, shoes} == set(look["owned"]) for look in looks)


def test_recommendations_stay_catalog_only(client, catalog, api):
    user = _user(client)
    _garment(client, user)
    body = _post(api, "complete", user, items=ITEMS, gender="women", n=3).json()
    assert body["recs"] and all(rec["item"]["i"] < len(CATEGORIES) for rec in body["recs"])
    assert all(not rec["item"].get("owned") for rec in body["recs"])


def test_users_cannot_see_each_others_pieces(client, catalog, api):
    alice, bob = _user(client), _user(client)
    alice_id = _garment(client, alice)
    bob_id = _garment(client, bob)
    text = _post(api, "complete", alice, items=ITEMS, gender="women", n=1).text
    assert str(alice_id) in text and str(bob_id) not in text
    assert [p.public_id for p in wardrobe_owned.load_owned(bob.id)] == [bob_id]


def test_another_users_id_is_rejected_as_an_unknown_item(client, catalog, api):
    alice, bob = _user(client), _user(client)
    alice_id = _garment(client, alice)
    for path in ("analyze", "complete", "outfits"):
        assert _post(api, path, bob, items=ITEMS + [alice_id], gender="women").status_code == 400


def test_requests_leave_the_shared_catalog_untouched(client, catalog, api):
    user = _user(client)
    _garment(client, user)
    before = (catalog.EMB.copy(), catalog.CAT.copy(), json.dumps(catalog.BYCAT, sort_keys=True), catalog.scoring._S["E"].clone())
    assert _post(api, "complete", user, items=ITEMS, gender="women", n=1).status_code == 200
    assert np.array_equal(before[0], catalog.EMB) and np.array_equal(before[1], catalog.CAT)
    assert before[2] == json.dumps(catalog.BYCAT, sort_keys=True) and torch.equal(before[3], catalog.scoring._S["E"])
    assert max(catalog.scoring.sizes) == len(CATEGORIES) + 1


def test_owned_pieces_count_toward_the_three_piece_minimum(client, catalog, api):
    user = _user(client)
    _garment(client, user)
    assert _post(api, "complete", items=[0, 3], gender="women").status_code == 400
    assert _post(api, "complete", user, items=[0, 3], gender="women").status_code == 200


def test_analyze_counts_owned_pieces_and_keeps_style_out_of_the_way(client, catalog, api):
    user = _user(client)
    _garment(client, user, outfit_cat="bag", category="bag")
    body = _post(api, "analyze", user, items=[0], gender="women").json()
    assert body["counts"]["bag"] == 1 and body["counts"]["top"] == 1


def test_men_wardrobe_does_not_score_an_owned_dress(client, catalog, api):
    user = _user(client)
    public_id = _garment(client, user, outfit_cat="dress", category="jumpsuit")
    men = _post(api, "complete", user, items=ITEMS, gender="men", n=1).text
    assert str(public_id) not in men
    assert str(public_id) in _post(api, "outfits", user, items=[6, 9], gender="women").text


def test_accessories_and_missing_vectors_are_listed_but_not_scored(client, catalog, api):
    user = _user(client)
    other = _garment(client, user, outfit_cat="other", category="accessory")
    failed = _garment(client, user, vector=False, status="failed")
    listed = {piece.public_id for piece in wardrobe_owned.load_owned(user.id)}
    assert {other, failed} <= listed
    text = _post(api, "complete", user, items=ITEMS, gender="women", n=1).text
    assert str(other) not in text


def test_embedding_is_computed_once_with_the_given_encoder(client, catalog, monkeypatch):
    user = _user(client)
    _garment(client, user, vector=False)
    calls = []
    monkeypatch.setattr(wardrobe_owned, "LocalPrivateStorage", lambda: type("S", (), {"read": lambda self, key: b"png"})())

    def encode(raw):
        calls.append(raw)
        return np.ones(512, dtype=np.float32)

    assert wardrobe_owned.load_owned(user.id, encode)[0].vector is not None
    assert wardrobe_owned.load_owned(user.id, encode)[0].vector is not None
    assert calls == [b"png"]


def test_failed_embedding_keeps_the_garment_listed_without_retry_loops(client, catalog, monkeypatch):
    user = _user(client)
    _garment(client, user, vector=False)
    calls = []
    monkeypatch.setattr(wardrobe_owned, "LocalPrivateStorage", lambda: type("S", (), {"read": lambda self, key: b"png"})())

    def encode(raw):
        calls.append(raw)
        raise RuntimeError("broken")

    pieces = wardrobe_owned.load_owned(user.id, encode)
    assert len(pieces) == 1 and pieces[0].vector is None
    wardrobe_owned.load_owned(user.id, encode)
    assert len(calls) == 1


def test_garment_saved_before_the_integration_gets_a_profile(client, catalog):
    user = _user(client)
    _garment(client, user)
    with client.app.state.testing_session_factory() as db:
        db.delete(db.query(GarmentWardrobeProfile).one())
        db.commit()
    piece = wardrobe_owned.load_owned(user.id)[0]
    assert piece.category == "top" and piece.code.startswith("w_")
