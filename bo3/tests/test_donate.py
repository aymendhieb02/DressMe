"""Tests de donate.py : aucune requete reseau (Overpass et Nominatim sont remplaces)."""
import importlib, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
fastapi = pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

TOULOUSE = (43.6045, 1.4442)
ELEMENTS = [
    {"type": "node", "id": 1, "lat": 43.6100, "lon": 1.4500, "tags": {"amenity": "recycling", "recycling:clothes": "yes", "recycling:shoes": "yes", "addr:street": "Rue A", "addr:housenumber": "3", "addr:postcode": "31000", "addr:city": "Toulouse"}},
    {"type": "way", "id": 2, "center": {"lat": 43.6050, "lon": 1.4450}, "tags": {"name": "Emmaus", "shop": "charity", "opening_hours": "Mo-Sa 10:00-18:00"}},
    {"type": "node", "id": 3, "lat": 43.6100, "lon": 1.4500, "tags": {"amenity": "recycling"}},     # meme position que 1 : doublon ecarte
    {"type": "relation", "id": 4, "tags": {"name": "sans position"}},                                # pas de coordonnees : ignore
]


@pytest.fixture()
def d(monkeypatch):
    mod = importlib.import_module("donate")
    mod._overpass.cache_clear(); mod._geocode.cache_clear()
    calls = []
    monkeypatch.setattr(mod, "_overpass", lambda q: calls.append(q) or ELEMENTS)
    monkeypatch.setattr(mod, "_geocode", lambda a: (TOULOUSE[0], TOULOUSE[1], "Toulouse, France") if "toulouse" in a.lower() else None)
    app = fastapi.FastAPI(); app.include_router(mod.router)
    return TestClient(app), mod, calls


def test_causes_listed(d):
    c, _, _ = d
    ids = [x["id"] for x in c.get("/api/donate/causes").json()]
    assert ids == ["recycling", "charity_shop", "shelter"]


def test_places_sorted_by_distance_and_deduplicated(d):
    c, _, calls = d
    r = c.post("/api/donate/places", json={"cause": "charity_shop", "lat": TOULOUSE[0], "lon": TOULOUSE[1]}).json()
    assert [p["name"] for p in r["places"]] == ["Emmaus", "Collection point"]            # le plus proche d'abord, 3 ecarte (meme position), 4 ignore
    assert r["places"][0]["distance_m"] < r["places"][1]["distance_m"]
    assert r["places"][1]["address"] == "3 Rue A, 31000 Toulouse" and r["places"][1]["accepts_shoes"] is True and r["places"][0]["accepts_shoes"] is None
    assert "cannot tell which organisation needs" in r["note"] and "OpenStreetMap" in r["attribution"]
    assert 'shop"="charity' in calls[0] and "around:5000" in calls[0]


def test_address_is_geocoded_and_unknown_address_is_404(d):
    c, _, _ = d
    ok = c.post("/api/donate/places", json={"cause": "recycling", "address": "Place du Capitole, Toulouse"}).json()
    assert ok["location"]["label"] == "Toulouse, France" and ok["places"]
    assert c.post("/api/donate/places", json={"cause": "recycling", "address": "zzzz nowhere"}).status_code == 404


def test_bad_inputs(d):
    c, _, _ = d
    assert c.post("/api/donate/places", json={"cause": "refugees", "lat": 1, "lon": 1}).status_code == 400
    assert c.post("/api/donate/places", json={"cause": "recycling"}).status_code == 400
    assert c.post("/api/donate/places", json={"cause": "recycling", "lat": 200, "lon": 1}).status_code == 422


def test_widens_radius_once_when_nothing_found(d, monkeypatch):
    c, mod, _ = d
    seen = []
    monkeypatch.setattr(mod, "_overpass", lambda q: seen.append(q) or ([] if "around:5000" in q else ELEMENTS))
    r = c.post("/api/donate/places", json={"cause": "recycling", "lat": TOULOUSE[0], "lon": TOULOUSE[1]}).json()
    assert r["radius_km"] == 15 and r["places"] and len(seen) == 2


def test_service_down_is_a_clean_502(d, monkeypatch):
    import requests
    c, mod, _ = d
    def boom(*a): raise requests.ConnectionError("down")
    monkeypatch.setattr(mod, "_overpass", boom); monkeypatch.setattr(mod, "_nominatim_nearby", boom)
    r = c.post("/api/donate/places", json={"cause": "recycling", "lat": 43.6, "lon": 1.44})
    assert r.status_code == 502 and "unavailable" in r.json()["detail"]


def test_falls_back_to_nominatim_when_overpass_is_down(d, monkeypatch):
    import requests
    c, mod, _ = d
    def boom(q): raise requests.ConnectionError("down")
    monkeypatch.setattr(mod, "_overpass", boom)
    monkeypatch.setattr(mod, "_nominatim_nearby", lambda cause, lat, lon, km: ELEMENTS)
    r = c.post("/api/donate/places", json={"cause": "recycling", "lat": TOULOUSE[0], "lon": TOULOUSE[1]}).json()
    assert r["source"] == "nominatim" and r["places"] and "fewer places" in r["note"]


def test_overpass_result_is_marked_as_such(d):
    c, mod, _ = d
    r = c.post("/api/donate/places", json={"cause": "recycling", "lat": TOULOUSE[0], "lon": TOULOUSE[1]}).json()
    assert r["source"] == "overpass" and "fewer places" not in r["note"]


def test_nominatim_nearby_converts_and_filters(monkeypatch):
    mod = importlib.import_module("donate")
    mod._nominatim_nearby.cache_clear()
    sample = [
        {"lat": "43.61", "lon": "1.45", "category": "amenity", "type": "recycling", "name": "Point textile", "extratags": {"recycling:clothes": "yes"},
         "address": {"house_number": "3", "road": "Rue A", "postcode": "31000", "city": "Toulouse"}},
        {"lat": "43.62", "lon": "1.46", "category": "amenity", "type": "recycling", "name": "Verre", "extratags": {"recycling:glass": "yes"}, "address": {}},
        {"lat": "43.63", "lon": "1.47", "category": "shop", "type": "charity", "name": "Emmaus", "extratags": {}, "address": {"town": "Blagnac"}},
    ]
    seen = {}
    class R:
        def raise_for_status(s): pass
        def json(s): return sample
    def fake_get(url, **kw): seen.update(kw["params"]); return R()
    monkeypatch.setattr(mod.requests, "get", fake_get)
    out = mod._nominatim_nearby("recycling", 43.6, 1.44, 5)
    assert [e["tags"]["name"] for e in out] == ["Point textile"]                  # le conteneur a verre est ecarte
    assert out[0]["tags"]["addr:street"] == "Rue A" and out[0]["lat"] == 43.61
    assert seen["bounded"] == 1 and seen["q"] == "recycling"
    mod._nominatim_nearby.cache_clear()
    assert [e["tags"]["name"] for e in mod._nominatim_nearby("charity_shop", 43.6, 1.44, 5)] == ["Emmaus"]


def test_overpass_falls_back_to_next_server(monkeypatch):
    import requests
    mod = importlib.import_module("donate")
    mod._overpass.cache_clear()
    monkeypatch.setattr(mod, "OVERPASS_URLS", ["http://a", "http://b"]); monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    tried = []

    class R:
        def __init__(s, ok): s.ok = ok
        def raise_for_status(s): pass
        def json(s): return {"elements": [{"id": 1}]}

    def fake_post(url, **kw):
        tried.append(url)
        if url == "http://a":
            raise requests.ReadTimeout("slow")
        return R(True)
    monkeypatch.setattr(mod.requests, "post", fake_post)
    assert mod._overpass("q-fallback") == [{"id": 1}]
    assert tried == ["http://a", "http://b"]


def test_overpass_retries_rounds_then_gives_up(monkeypatch):
    import requests
    mod = importlib.import_module("donate")
    mod._overpass.cache_clear()
    monkeypatch.setattr(mod, "OVERPASS_URLS", ["http://a"]); monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    n = []
    def fake_post(url, **kw):
        n.append(url); raise requests.ReadTimeout("busy")
    monkeypatch.setattr(mod.requests, "post", fake_post)
    with pytest.raises(requests.RequestException):
        mod._overpass("q-giveup")
    assert len(n) == mod.OVERPASS_ROUNDS
