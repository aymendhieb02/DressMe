"""Tests du routeur redundancy.py avec le VRAI catalog.json de l'appli et des embeddings SYNTHETIQUES.

Les embeddings reels (data/emb_clip.npy) et les images ne sont pas necessaires : un faux module `api` fournit les memes
attributs que api.py (CODES, DESC, CAT, EMB, BYCAT, CATS, DATA, it). Ces tests verifient la logique et le format
des reponses, pas la qualite des seuils sur les vrais embeddings (voir calibrate_bo3.py).
"""
import importlib, json, sys, types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
fastapi = pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

CAT_JSON = json.load(open(Path(__file__).parent / "fixtures" / "app_catalog.json"))
N = len(CAT_JSON["codes"])
PLANTED = []   # (source, copie) : quasi-doublons plantes


def build_fake_api(tmp_path):
    rng = np.random.default_rng(0)
    cats = CAT_JSON["cat"]
    centers = {c: rng.normal(size=512) for c in set(cats)}
    E = np.array([centers[c] * 1.0 + rng.normal(size=512) * 0.6 for c in cats], dtype=np.float32)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    PLANTED.clear()
    from redundancy import type_of
    tlist = [type_of(g, d) for g, d in zip(cats, CAT_JSON["desc"])]
    def two(t, k=0):      # deux pieces du meme type (le routeur ne compare que des pieces de meme type)
        ids = [i for i, x in enumerate(tlist) if x == t]; return ids[2 * k], ids[2 * k + 1]
    for src, dup in [two("top/Knitwear", 0), two("top/Knitwear", 1), two("shoes/Sneakers")]:
        E[dup] = E[src] + rng.normal(size=512).astype(np.float32) * 0.01; E[dup] /= np.linalg.norm(E[dup]); PLANTED.append((src, dup))
    m = types.ModuleType("api")
    m.CODES, m.DESC, m.CAT, m.EMB = CAT_JSON["codes"], CAT_JSON["desc"], cats, E
    m.CATS = ["shoes", "bag", "dress", "outer", "top", "bottom", "other"]
    m.BYCAT = {c: [i for i, x in enumerate(cats) if x == c] for c in set(cats)}
    m.DATA = tmp_path
    m.it = lambda i: dict(i=i, c=cats[i], d=m.DESC[i], k=m.CODES[i])
    return m


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRESSME_DATA", str(tmp_path))
    monkeypatch.setitem(sys.modules, "api", build_fake_api(tmp_path))
    sys.modules.pop("redundancy", None)
    red = importlib.import_module("redundancy"); red.engine.cache_clear(); red.types.cache_clear()
    app = fastapi.FastAPI(); app.include_router(red.router)
    return TestClient(app), red


def wardrobe_with_planted(n=30):
    base = [s for s, _ in PLANTED] + [d for _, d in PLANTED]
    rest = [i for i in range(N) if i not in base][: n - len(base)]
    return base + rest


def test_colour_parsing_on_real_descriptions(client):
    _, red = client
    cols = [red.colour_of(d) for d in CAT_JSON["desc"]]
    assert red.colour_of("white floral silk-blend top") == "white"
    assert red.colour_of("dark blue double-breasted cotton cardigan") == "blue"
    assert red.colour_of("multicoloured jacquard virgin wool cardigan") is None
    assert sum(c is not None for c in cols) >= 150   # ~97 % des articles ont une couleur de la palette


def test_analyse_finds_planted_duplicates(client):
    c, _ = client
    r = c.post("/api/redundancy/analyse", json={"items": wardrobe_with_planted()}).json()
    found = {frozenset(i["i"] for i in g["items"]) for g in r["duplicate_groups"]}
    for s, d in PLANTED:
        assert frozenset({s, d}) in found
    assert r["clutter"]["score100"] >= round(100 * 3 / 30)
    assert r["clutter"]["level"] in ("sain", "quelques redondances", "fort encombrement")
    assert "source" in r["thresholds"] and r["thresholds"]["T_DUP"] > r["thresholds"]["T_SIM"]
    assert r["n_items"] == 30
    assert all(g["same_colour"] in (True, False, None) for g in r["duplicate_groups"])
    json.dumps(r)    # serialisable


def test_small_wardrobe_warns(client):
    c, _ = client
    r = c.post("/api/redundancy/analyse", json={"items": [0, 1, 2, 3]}).json()
    assert any("20 articles" in w for w in r["warnings"])


def test_purchase_check_doublon_and_nouveau(client):
    c, _ = client
    wardrobe = [s for s, _ in PLANTED] + [i for i in range(N) if i not in {x for p in PLANTED for x in p}][:25]
    dup_of_first = PLANTED[0][1]            # quasi-copie de wardrobe[0], absente de la garde-robe
    r = c.post("/api/redundancy/analyse", json={"items": wardrobe, "candidate": dup_of_first}).json()
    pc = r["purchase_check"]
    assert pc["verdict"] == "DOUBLON" and pc["nearest"]["i"] == PLANTED[0][0]
    planted_ids = {x for p in PLANTED for x in p}
    other = next(i for i in range(N) if i not in wardrobe and i not in planted_ids and CAT_JSON['cat'][i] == 'bottom')
    assert other not in wardrobe
    r2 = c.post("/api/redundancy/analyse", json={"items": wardrobe, "candidate": other}).json()
    assert r2["purchase_check"]["verdict"] in ("NOUVEAU", "SIMILAIRE")


@pytest.mark.parametrize("body", [{"items": []}, {"items": [0, 99999]}, {"items": [-1]}, {"items": [0, 1], "candidate": 0}, {"items": [0], "candidate": 99999}])
def test_bad_requests_return_400(client, body):
    c, _ = client
    assert c.post("/api/redundancy/analyse", json=body).status_code == 400


def test_duplicate_indices_are_ignored(client):
    c, _ = client
    r = c.post("/api/redundancy/analyse", json={"items": [0, 0, 1, 1, 2]}).json()
    assert r["n_items"] == 3


def test_example_wardrobe_is_big_enough_and_contains_close_pairs(client):
    c, _ = client
    items = c.get("/api/redundancy/example").json()["items"]
    ids = [x["i"] for x in items]
    assert len(ids) >= 20 and len(set(ids)) == len(ids)
    r = c.post("/api/redundancy/analyse", json={"items": ids}).json()
    assert r["clutter"]["score100"] > 0 and r["duplicate_groups"]


def test_thresholds_file_is_used_when_present(client, tmp_path):
    c, red = client
    (tmp_path / "bo3_thresholds.json").write_text(json.dumps({"T_DUP": 0.97, "T_SIM": 0.9, "source": "test"}))
    red.engine.cache_clear()
    th = c.post("/api/redundancy/analyse", json={"items": [0, 1, 2]}).json()["thresholds"]
    assert (th["T_DUP"], th["T_SIM"], th["source"]) == (0.97, 0.9, "test")


def test_provisional_thresholds_are_flagged(client):
    c, _ = client
    th = c.post("/api/redundancy/analyse", json={"items": [0, 1, 2]}).json()["thresholds"]
    assert "provisional" in th["source"] and th["T_SIM"] < th["T_DUP"] <= 1.0 and th["T_DUP"] >= 0.92


def test_colour_map_flags_a_planted_concentration(client):
    """Tous les hauts noirs du catalogue (5) + 20 autres pieces : la carte doit signaler (top, black)."""
    c, red = client
    cats, desc = CAT_JSON["cat"], CAT_JSON["desc"]
    black_tops = [i for i, (x, d) in enumerate(zip(cats, desc)) if x == "top" and red.colour_of(d) == "black"]
    rest = [i for i in range(N) if i not in black_tops and not (cats[i] == "top" and red.colour_of(desc[i]) == "black")][:20]
    r = c.post("/api/redundancy/analyse", json={"items": black_tops + rest}).json()
    assert any(f["category"] == "top" and f["colour"] == "black" for f in r["colour_map"]["flagged"])


def test_calibrate_thresholds_matches_notebook_method():
    from bo3.bo3_service import calibrate_thresholds
    rng = np.random.default_rng(1)
    pos, neg = rng.normal(0.95, 0.02, 200), rng.normal(0.75, 0.08, 4000)
    t_dup, t_sim, f1 = calibrate_thresholds(pos, neg)
    assert 0.75 < t_sim < t_dup < 0.95 and f1 > 0.8
    sk = pytest.importorskip("sklearn.metrics")
    y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]; s = np.r_[pos, neg]
    P, R, T = sk.precision_recall_curve(y, s); F1 = 2 * P[:-1] * R[:-1] / (P[:-1] + R[:-1] + 1e-9)
    ok = np.where(F1 >= F1.max() - 1e-9)[0]
    assert abs(t_dup - (T[ok[0]] + T[ok[-1]]) / 2) < 0.02


def test_same_colour_flag(client):
    _, red = client
    assert red.same_colour(["black", "black"]) is True
    assert red.same_colour(["black", "blue"]) is False
    assert red.same_colour(["black", None]) is None


def test_types_split_broad_categories(client):
    """bottom = pantalons + jupes + shorts dans l'appli : le routeur ne doit comparer que des pieces de meme type."""
    _, red = client
    t = red.types()
    assert "bottom/Skirts" in t and "bottom/Pants" in t and "top/T-shirts" in t and "shoes/Sneakers" in t
    assert t[CAT_JSON["desc"].index("white mid-rise midi skirt")] == "bottom/Skirts"
    assert red.type_of("top", "white striped cotton henley T-shirt") == "top/T-shirts"
    assert red.type_of("top", "blue cotton piqu\u00e9 polo shirt") == "top/Polos"
    assert red.type_of("dress", "black silk satin T-shirt dress") == "dress"      # pas de sous-type : categorie large


def test_skirt_is_not_compared_with_pants(client):
    c, red = client
    d = CAT_JSON["desc"]
    pants = [i for i, x in enumerate(red.types()) if x == "bottom/Pants"][:6]
    skirt = next(i for i, x in enumerate(red.types()) if x == "bottom/Skirts")
    r = c.post("/api/redundancy/analyse", json={"items": pants, "candidate": skirt}).json()
    pc = r["purchase_check"]
    assert pc["verdict"] == "NOUVEAU" and "nearest" not in pc and pc["nearest_index"] is None


def test_group_labels_are_readable(client):
    c, _ = client
    r = c.post("/api/redundancy/analyse", json={"items": wardrobe_with_planted()}).json()
    assert all("/" not in g["category"] for g in r["duplicate_groups"])
    assert all("/" not in x["category"] for x in r["clutter"]["by_category"])


# ---- zone grise : question a l'utilisatrice (trois seuils T_SIM < T_GRISE < T_DUP) ---------------------------------------
def _grey_pair(red, a):
    """Deux pieces de meme type fin du faux catalogue dont le cosinus tombe dans la zone grise (seuils ecrits dans le test)."""
    E = a.EMB; ts = red.types(); idx = [i for i, t in enumerate(ts) if t == "top/Knitwear"]
    x, y = [i for i in idx if i not in {p for pair in PLANTED for p in pair}][:2]
    rng = np.random.default_rng(5); u = rng.normal(size=E.shape[1]).astype(np.float32); u -= (u @ E[x]) * E[x]; u /= np.linalg.norm(u)
    cos = 0.93
    E[y] = cos * E[x] + np.sqrt(1 - cos ** 2) * u; E[y] /= np.linalg.norm(E[y])
    return x, y


def _client_with_grey(client, tmp_path):
    c, red = client
    (tmp_path / "bo3_thresholds.json").write_text(json.dumps({"T_DUP": 0.96, "T_SIM": 0.85, "T_GRISE": 0.90, "source": "test"}))
    red.engine.cache_clear()
    x, y = _grey_pair(red, sys.modules["api"])
    return c, x, y


def test_grey_zone_pair_is_returned_with_the_fixed_question(client, tmp_path):
    c, x, y = _client_with_grey(client, tmp_path)
    r = c.post("/api/redundancy/analyse", json={"items": [x, y] + wardrobe_with_planted()[:20]}).json()
    assert r["question"] == "Do you consider these two pieces redundant?"
    pairs = [{q["items"][0]["i"], q["items"][1]["i"]} for q in r["to_confirm"]]
    assert {x, y} in pairs and r["thresholds"]["T_GRISE"] == 0.9


def test_answers_are_taken_into_account(client, tmp_path):
    c, x, y = _client_with_grey(client, tmp_path)
    base = [x, y] + wardrobe_with_planted()[:20]
    yes = c.post("/api/redundancy/analyse", json={"items": base, "answers": [{"a": x, "b": y, "redundant": True}]}).json()
    assert all({q["items"][0]["i"], q["items"][1]["i"]} != {x, y} for q in yes["to_confirm"])
    assert any({i["i"] for i in g["items"]} >= {x, y} for g in yes["duplicate_groups"])
    no = c.post("/api/redundancy/analyse", json={"items": base, "answers": [{"a": y, "b": x, "redundant": False}]}).json()
    assert all({q["items"][0]["i"], q["items"][1]["i"]} != {x, y} for q in no["to_confirm"])
    assert not any({i["i"] for i in g["items"]} >= {x, y} for g in no["duplicate_groups"])


def test_candidate_in_grey_zone_gets_the_question(client, tmp_path):
    c, x, y = _client_with_grey(client, tmp_path)
    r = c.post("/api/redundancy/analyse", json={"items": [x] + wardrobe_with_planted()[:20], "candidate": y}).json()
    pc = r["purchase_check"]
    assert pc["verdict"] == "A_CONFIRMER" and pc["question"] == "Do you consider these two pieces redundant?" and pc["nearest"]["i"] == x


def test_missing_grise_is_derived_between_the_other_two(client, tmp_path):
    c, red = client
    (tmp_path / "bo3_thresholds.json").write_text(json.dumps({"T_DUP": 0.96, "T_SIM": 0.85, "source": "test"}))
    red.engine.cache_clear()
    th = c.post("/api/redundancy/analyse", json={"items": [0, 1, 2]}).json()["thresholds"]
    assert 0.85 < th["T_GRISE"] < 0.96 and "provisional" in th["T_GRISE_source"]


def test_example_wardrobe_is_big_enough_and_shows_a_colour_concentration(client):
    client = client[0]
    ids = [x["i"] for x in client.get("/api/redundancy/example").json()["items"]]
    assert len(ids) >= 30 and len(set(ids)) == len(ids)
    r = client.post("/api/redundancy/analyse", json={"items": ids}).json()
    assert not any("20 articles" in w or "30 articles" in w for w in r["warnings"])
    cm = r["colour_map"]
    assert cm["cells"] and cm["palette"] and cm["groups"] and all("category" in c for c in cm["cells"])
    assert cm["flagged"], "l'exemple doit montrer au moins une concentration de couleur"


def test_engine_uses_colour_fusion_when_calibrated_with_pixels(client):
    """data/bo3_thresholds.json avec beta + data/bo3_colour_lab.npy : une coupe identique de couleur differente n'est plus un doublon."""
    c, red = client
    s, d = PLANTED[0]
    base = np.tile(np.array([50.0, 0, 0], dtype=np.float32), (N, 1))
    json.dump(dict(T_DUP=0.9, T_SIM=0.8, T_GRISE=0.86, beta=0.15, model="fashionclip", source="test"), open(red.DATA / "bo3_thresholds.json", "w"))
    items = [s, d]
    def run(labs):
        np.save(red.DATA / "bo3_colour_lab.npy", labs)
        red.labs.cache_clear(); red.engine.cache_clear()
        return c.post("/api/redundancy/analyse", json={"items": items}).json()
    r1 = run(base)                                                   # meme couleur : doublon
    assert len(r1["duplicate_groups"]) == 1 and r1["thresholds"]["beta"] == 0.15
    other = base.copy(); other[d] = [95.0, 40.0, 40.0]               # meme coupe, couleur tres differente
    r2 = run(other)
    assert r2["duplicate_groups"] == []


def test_engine_colour_rule_end_to_end(client):
    """beta = 0 + colour_tau dans le fichier de seuils : meme coupe de couleur tres differente -> a confirmer (pas de doublon), meme couleur -> doublon."""
    c, red = client
    s, d = PLANTED[0]
    base = np.tile(np.array([50.0, 0, 0], dtype=np.float32), (N, 1))
    json.dump(dict(T_DUP=0.9, T_SIM=0.8, T_GRISE=0.86, beta=0.0, colour_tau=20.0, model="fashionclip", source="test"), open(red.DATA / "bo3_thresholds.json", "w"))
    def run(labs):
        np.save(red.DATA / "bo3_colour_lab.npy", labs)
        red.labs.cache_clear(); red.engine.cache_clear()
        return c.post("/api/redundancy/analyse", json={"items": [s, d]}).json()
    r1 = run(base)
    assert len(r1["duplicate_groups"]) == 1 and r1["thresholds"]["colour_tau"] == 20.0 and r1["thresholds"]["beta"] == 0.0
    assert r1["duplicate_groups"][0]["same_colour"] is True                # etiquette lue sur les pixels
    other = base.copy(); other[d] = [95.0, 40.0, 40.0]
    r2 = run(other)
    assert r2["duplicate_groups"] == [] and [q["reason"] for q in r2["to_confirm"]] == ["colour"]
    assert len(r2["to_confirm"][0]["items"]) == 2          # le routeur renvoie les pieces completes pour l'affichage


def test_same_colour_label_uses_pixels_not_description(client):
    """Une description dit 'blue' pour deux pieces, mais les pixels sont tres differents : l'etiquette doit dire 'different colour'."""
    c, red = client
    s, d = PLANTED[0]
    json.dump(dict(T_DUP=0.9, T_SIM=0.8, T_GRISE=0.86, beta=0.0, colour_tau=20.0, model="fashionclip", source="test"), open(red.DATA / "bo3_thresholds.json", "w"))
    labs = np.tile(np.array([50.0, 0, 0], dtype=np.float32), (N, 1)); labs[d] = [95.0, 40.0, 40.0]
    np.save(red.DATA / "bo3_colour_lab.npy", labs); red.labs.cache_clear(); red.engine.cache_clear()
    r = c.post("/api/redundancy/analyse", json={"items": [s, d], "answers": [{"a": s, "b": d, "redundant": True}]}).json()
    assert len(r["duplicate_groups"]) == 1 and r["duplicate_groups"][0]["same_colour"] is False
