"""Tests de bon sens pour bo3_service (aucun telechargement de modele : embeddings pre-calcules dans tests/fixtures)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bo3_service import BO3  # noqa: E402

F = Path(__file__).parent / "fixtures"
E = np.load(F / "emb_catalog_fashionclip.npy")
A = np.load(F / "emb_aug_fashionclip.npy")
SRC = np.load(F / "aug_src_idx.npy")
CAT = pd.read_csv(F / "catalog_ids.csv")
TYPES = CAT.articleType.values
COL = pd.read_csv(F / "colours_catalogue.csv").drop_duplicates("id").set_index("id")


@pytest.fixture(scope="module")
def bo3():
    return BO3()


def items(idx):
    out = []
    for i in idx:
        id_ = int(CAT.id[i])
        out.append(dict(item_id=id_, category=TYPES[i], colour=COL.loc[id_, "couleur"] if id_ in COL.index else None, embedding=E[i]))
    return out


def wardrobe_with_dups(rng, k, n=40):
    pick = rng.choice(len(A), size=k, replace=False) if k else np.array([], dtype=int)
    base = list(dict.fromkeys(SRC[pick].tolist()))
    pool = [i for i in range(len(E)) if i not in base]
    fill = list(rng.choice(pool, size=max(n - k - len(base), 0), replace=False))
    return items(base + fill) + [dict(item_id=100000 + int(r), category=TYPES[SRC[r]], colour=None, embedding=A[r]) for r in pick]


def test_thresholds_loaded(bo3):
    assert bo3.model == "fashionclip"
    assert bo3.t_sim < bo3.t_dup <= 1
    assert abs(bo3.t_dup - 0.885) < 0.01
    assert bo3.beta == 0.0                      # fusion couleur non validee : desactivee par defaut


def test_duplicate_copy_triggers_alert(bo3):
    ok = [bo3.purchase_check(A[r] / np.linalg.norm(A[r]), TYPES[SRC[r]], E / np.linalg.norm(E, axis=1, keepdims=True), TYPES)["verdict"] == "DOUBLON"
          for r in range(len(A))]
    assert np.mean(ok) >= 0.85                  # mesure : 0,92


def test_unrelated_category_is_new(bo3):
    En = E / np.linalg.norm(E, axis=1, keepdims=True)
    r = bo3.purchase_check(En[0], "Categorie inconnue", En, TYPES)
    assert r["verdict"] == "NOUVEAU" and r["nearest_index"] is None


def test_wardrobe_without_duplicates_is_mostly_healthy(bo3):
    rng = np.random.default_rng(0)
    res = [bo3.analyse_wardrobe(items(rng.choice(len(E), 40, replace=False)))["clutter"] for _ in range(100)]
    assert np.mean([r["level"] == "sain" for r in res]) >= 0.9     # mesure : 0,97
    assert np.mean([r["score100"] for r in res]) < 6


def test_planted_duplicates_raise_score(bo3):
    rng = np.random.default_rng(1)
    s0 = np.mean([bo3.analyse_wardrobe(wardrobe_with_dups(rng, 0))["clutter"]["score100"] for _ in range(40)])
    s8 = np.mean([bo3.analyse_wardrobe(wardrobe_with_dups(rng, 8))["clutter"]["score100"] for _ in range(40)])
    assert s8 >= 15 and s8 > 3 * max(s0, 1)


def test_levels_are_mostly_correct(bo3):
    rng = np.random.default_rng(2)
    exp = lambda k: "sain" if k <= 2 else ("quelques redondances" if k <= 6 else "fort encombrement")
    ok = [bo3.analyse_wardrobe(wardrobe_with_dups(rng, k))["clutter"]["level"] == exp(k) for k in (0, 2, 4, 6, 8, 10) for _ in range(30)]
    assert np.mean(ok) >= 0.75                  # mesure : 0,86 (niveaux 10/20 provisoires)


def test_same_category_gating_never_increases_score(bo3):
    rng = np.random.default_rng(3)
    for _ in range(30):
        its = items(rng.choice(len(E), 40, replace=False))
        assert bo3.analyse_wardrobe(its, same_category=True)["clutter"]["score100"] <= bo3.analyse_wardrobe(its, same_category=False)["clutter"]["score100"]


def test_deterministic(bo3):
    its = wardrobe_with_dups(np.random.default_rng(4), 6)
    assert bo3.analyse_wardrobe(its) == bo3.analyse_wardrobe(its)


def test_output_is_json_serialisable(bo3):
    its = wardrobe_with_dups(np.random.default_rng(5), 6)
    r = bo3.analyse_wardrobe(its, candidate=dict(item_id="new", category=TYPES[SRC[0]], embedding=A[0]))
    json.dumps(r)
    assert r["purchase_check"]["verdict"] in {"DOUBLON", "A_CONFIRMER", "SIMILAIRE", "NOUVEAU"}


def _sample_reference(bo3, rng, n=40):
    P = bo3.ref.values.ravel() / bo3.ref.values.sum()
    cnt = rng.multinomial(n, P).reshape(bo3.ref.shape)
    g, c = [], []
    for i, j in zip(*np.nonzero(cnt)):
        g += [bo3.ref.index[i]] * cnt[i, j]
        c += [bo3.ref.columns[j]] * cnt[i, j]
    return g, c


def test_colour_map_false_alarm_rate_is_low(bo3):
    rng = np.random.default_rng(6)
    fa = np.mean([len(bo3.colour_map(*_sample_reference(bo3, rng))["flagged"]) > 0 for _ in range(1000)])
    assert fa <= 0.05                           # mesure : 0,008


def test_colour_map_detects_strong_concentration(bo3):
    rng = np.random.default_rng(7)
    hits = []
    for _ in range(200):
        g, c = _sample_reference(bo3, rng, 25)
        hits.append(any(x["group"] == "Hauts" and x["colour"] == "Noir" for x in bo3.colour_map(g + ["Hauts"] * 15, c + ["Noir"] * 15)["flagged"]))
    assert np.mean(hits) >= 0.9                 # 15 hauts noirs sur 40 (37 %)


def test_edge_cases_and_warnings(bo3):
    assert bo3.analyse_wardrobe([])["n_items"] == 0
    r = bo3.analyse_wardrobe(items(range(10)))
    assert any("moins de 20" in w for w in r["warnings"])
    its = items(range(40)); its[0]["colour"] = "Couleur inconnue"
    assert any("exclus de la carte" in w for w in bo3.analyse_wardrobe(its)["warnings"])


# ---- trois seuils, zone grise, reponses de l'utilisatrice, comparaison par categorie -----------------------------------
def test_three_thresholds_are_ordered(bo3):
    assert bo3.t_sim < bo3.t_grise < bo3.t_dup
    assert abs(bo3.t_grise - 0.851) < 1e-6            # T_GRISE de l'etude (155 paires annotees de meme categorie)


def test_zone_of_covers_the_four_zones(bo3):
    z = bo3.zone_of
    assert z(bo3.t_sim - 0.01) == "DISTINCT" and z(bo3.t_sim) == "SIMILAR" and z(bo3.t_grise) == "TO_CONFIRM" and z(bo3.t_dup) == "DUPLICATE"


def _unit(v):
    return v / np.linalg.norm(v)


def _pair_at(cos, rng):
    a = _unit(rng.normal(size=512)); u = rng.normal(size=512); u -= (u @ a) * a; u = _unit(u)
    return a.astype(np.float32), (cos * a + np.sqrt(1 - cos ** 2) * u).astype(np.float32)


def _two_items(cos, cat_a="Jeans", cat_b="Jeans", seed=0):
    a, b = _pair_at(cos, np.random.default_rng(seed))
    return [dict(item_id=1, category=cat_a, colour=None, embedding=a), dict(item_id=2, category=cat_b, colour=None, embedding=b)]


def test_grey_zone_pair_is_asked_with_the_fixed_question(bo3):
    r = bo3.analyse_wardrobe(_two_items((bo3.t_grise + bo3.t_dup) / 2))
    assert r["question"] == "Do you consider these two pieces redundant?"
    assert [q["item_ids"] for q in r["to_confirm"]] == [[1, 2]] and r["duplicate_groups"] == []


def test_similar_band_is_not_asked(bo3):
    r = bo3.analyse_wardrobe(_two_items((bo3.t_sim + bo3.t_grise) / 2))
    assert r["to_confirm"] == [] and r["duplicate_groups"] == [] and r["n_similar_pairs"] == 1


def test_answer_yes_makes_a_group_and_removes_the_question(bo3):
    cos = (bo3.t_grise + bo3.t_dup) / 2
    r = bo3.analyse_wardrobe(_two_items(cos), answers=[{"a": 1, "b": 2, "redundant": True}])
    assert r["to_confirm"] == [] and len(r["duplicate_groups"]) == 1 and r["clutter"]["score100"] == 50


def test_answer_no_removes_the_question_without_group(bo3):
    cos = (bo3.t_grise + bo3.t_dup) / 2
    r = bo3.analyse_wardrobe(_two_items(cos), answers=[{"a": 2, "b": 1, "redundant": False}])
    assert r["to_confirm"] == [] and r["duplicate_groups"] == [] and r["clutter"]["score100"] == 0


def test_different_categories_are_never_compared(bo3):
    r = bo3.analyse_wardrobe(_two_items(0.97, "Skirts", "Trousers"))
    assert r["to_confirm"] == [] and r["duplicate_groups"] == [] and r["n_similar_pairs"] == 0


def test_purchase_check_grey_zone_returns_question(bo3):
    a, b = _pair_at((bo3.t_grise + bo3.t_dup) / 2, np.random.default_rng(3))
    r = bo3.purchase_check(b, "Jeans", a[None], np.array(["Jeans"], dtype=object))
    assert r["verdict"] == "A_CONFIRMER" and r["question"] == "Do you consider these two pieces redundant?"
    r2 = bo3.purchase_check(b, "Skirts", a[None], np.array(["Jeans"], dtype=object))
    assert r2["verdict"] == "NOUVEAU" and r2["nearest_index"] is None


def test_grise_is_derived_when_missing():
    from bo3_service import grise_from
    b = BO3(t_dup=0.95, t_sim=0.85)
    assert b.t_sim < b.t_grise < b.t_dup and abs(b.t_grise - grise_from(0.85, 0.95)) < 1e-9 and "provisional" in b.grise_source


def test_calibrate_fashionclip_flow_with_fake_encoder():
    """calibrate() : doublons fabriques -> rappel eleve, seuils ordonnes, controles par zone presents (encodeur factice, sans torch)."""
    import importlib.util, numpy as np
    from PIL import Image
    spec = importlib.util.spec_from_file_location("calibrate_bo3", Path(__file__).resolve().parents[1] / "calibrate_bo3.py")
    cal = importlib.util.module_from_spec(spec); spec.loader.exec_module(cal)
    rng = np.random.default_rng(1)
    imgs = [Image.fromarray(rng.integers(0, 255, (48, 48, 3), dtype=np.uint8)).resize((48, 48)) for _ in range(60)]
    def encode(ims):
        v = np.stack([np.asarray(i.resize((6, 6)), dtype=np.float32).ravel() for i in ims]); v -= 128.0
        return v / np.linalg.norm(v, axis=1, keepdims=True)
    E, L, out = cal.calibrate(imgs, encode, {"top": list(range(30)), "bottom": list(range(30, 60))}, n_aug=40, n_neg=500)
    assert E.shape[0] == 60 and out["model"] == "fashionclip" and out["beta"] == 0.0 and out["colour_tau"] >= 10.0
    assert out["T_SIM"] < out["T_GRISE"] < out["T_DUP"]
    assert set(out["checks"]) >= {"recall_doublons_fabriques", "meme_type_doublon", "meme_type_zone_grise", "meme_type_similaire"}
    assert out["checks"]["recall_doublons_fabriques"] > 0.5


def test_calibrate_sweep_compares_betas_without_writing(tmp_path, monkeypatch):
    import importlib.util, numpy as np
    from PIL import Image
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("calibrate_bo3", Path(__file__).resolve().parents[1] / "calibrate_bo3.py")
    cal = importlib.util.module_from_spec(spec); spec.loader.exec_module(cal)
    rng = np.random.default_rng(1)
    imgs = [Image.fromarray(rng.integers(0, 255, (48, 48, 3), dtype=np.uint8)) for _ in range(60)]
    calls = []
    def encode(ims):
        calls.append(len(ims))
        v = np.stack([np.asarray(i.resize((6, 6)), dtype=np.float32).ravel() for i in ims]); v -= 128.0
        return v / np.linalg.norm(v, axis=1, keepdims=True)
    res = cal.sweep(imgs, encode, {"top": list(range(30)), "bottom": list(range(30, 60))}, betas=(0.0, 0.15), n_aug=40, n_neg=500)
    assert set(res) == {0.0, 0.15} and all(o["T_SIM"] < o["T_DUP"] for o in res.values())
    assert sum(calls) == 60 + 40                       # catalogue + variantes : encodes une seule fois malgre deux beta
    assert list(tmp_path.iterdir()) == []              # rien n'est ecrit
    cal.print_sweep(res)


def _same_cut(lab_a, lab_b):
    return [dict(item_id=1, category="Knitwear", colour=None, embedding=E[0], lab=lab_a),
            dict(item_id=2, category="Knitwear", colour=None, embedding=E[0], lab=lab_b)]


def test_colour_fusion_same_cut_different_colour_is_not_a_duplicate():
    black, white = np.array([10.0, 0, 0]), np.array([95.0, 0, 0])
    plain, fused = BO3(beta=0.0), BO3(beta=0.15)
    assert len(plain.analyse_wardrobe(_same_cut(black, white))["duplicate_groups"]) == 1      # sans couleur : meme embedding = doublon
    assert fused.analyse_wardrobe(_same_cut(black, white))["duplicate_groups"] == []          # avec couleur : coupe identique, couleur differente
    assert len(fused.analyse_wardrobe(_same_cut(black, black))["duplicate_groups"]) == 1      # meme couleur : toujours doublon


def test_no_question_for_two_pieces_already_in_the_same_group():
    """A~B et B~C sont des doublons ; A~C est en zone grise. A et C sont deja dans le meme groupe : on ne pose pas la question."""
    th = np.deg2rad(22.0)
    emb = [np.array([np.cos(-th), np.sin(-th), 0.0]), np.array([1.0, 0.0, 0.0]), np.array([np.cos(th), np.sin(th), 0.0])]
    items = [dict(item_id=k + 1, category="T-shirts", colour=None, embedding=emb[k]) for k in range(3)]
    b = BO3(beta=0.0, t_dup=0.9, t_sim=0.6, t_grise=0.7)
    r = b.analyse_wardrobe(items)
    assert [sorted(g["item_ids"]) for g in r["duplicate_groups"]] == [[1, 2, 3]]
    assert r["to_confirm"] == []
    far = b.analyse_wardrobe([items[0], items[2]])             # sans B : A~C seul est bien une question
    assert far["duplicate_groups"] == [] and len(far["to_confirm"]) == 1


def test_colour_of_white_garment_is_white_even_with_a_few_dark_pixels():
    """Chemise blanche avec un petit logo sombre (~60 pixels a 64x64) : sa couleur doit rester blanche, pas sombre."""
    from PIL import Image
    from bo3.bo3_service import colour_lab
    im = Image.new("RGB", (256, 256), (255, 255, 255)); px = im.load()
    for x0 in range(100, 124):
        for y0 in range(120, 130): px[x0, y0] = (20, 20, 20)           # logo sombre : ~15 pixels a 64x64... plus les ombres ci-dessous
    for x0 in range(60, 200):
        for y0 in (80, 81, 82, 83, 200, 201, 202, 203): px[x0, y0] = (40, 40, 40)   # plis/ombres sombres : > 50 pixels non blancs une fois reduit
    assert colour_lab(im)[0] > 85
    red = Image.new("RGB", (256, 256), (255, 255, 255)); q = red.load()
    for x0 in range(40, 216):
        for y0 in range(40, 216): q[x0, y0] = (200, 30, 30)
    lab = colour_lab(red)
    assert 35 < lab[0] < 60 and lab[1] > 40                              # un vetement colore garde sa couleur


def _veto_items(lab_a, lab_b):
    return [dict(item_id=1, category="Knitwear", colour=None, embedding=E[0], lab=lab_a),
            dict(item_id=2, category="Knitwear", colour=None, embedding=E[0], lab=lab_b)]


def test_colour_rule_downgrades_same_cut_different_colour_to_confirm():
    black, white = np.array([10.0, 0, 0]), np.array([95.0, 0, 0])
    b = BO3(beta=0.0, colour_tau=20.0)
    r = b.analyse_wardrobe(_veto_items(black, white))
    assert r["duplicate_groups"] == []                                   # pas de doublon automatique
    assert [q["reason"] for q in r["to_confirm"]] == ["colour"]           # mais on demande
    assert len(b.analyse_wardrobe(_veto_items(black, black))["duplicate_groups"]) == 1     # meme couleur : doublon
    assert len(BO3(beta=0.0).analyse_wardrobe(_veto_items(black, white))["duplicate_groups"]) == 1   # sans regle : comme avant


def test_colour_rule_user_yes_still_groups_the_pair():
    black, white = np.array([10.0, 0, 0]), np.array([95.0, 0, 0])
    r = BO3(beta=0.0, colour_tau=20.0).analyse_wardrobe(_veto_items(black, white), answers=[{"a": 1, "b": 2, "redundant": True}])
    assert len(r["duplicate_groups"]) == 1 and r["to_confirm"] == []


def test_colour_rule_in_purchase_check():
    b = BO3(beta=0.0, colour_tau=20.0)
    black, white = np.array([10.0, 0, 0]), np.array([95.0, 0, 0])
    Es = E[:1]; cats = np.array(["Knitwear"], dtype=object)
    r = b.purchase_check(E[0], "Knitwear", Es, cats, cand_lab=white, labs=np.array([black]))
    assert r["verdict"] == "A_CONFIRMER" and r["reason"] == "colour"
    assert b.purchase_check(E[0], "Knitwear", Es, cats, cand_lab=black, labs=np.array([black]))["verdict"] == "DOUBLON"


def test_colour_fusion_in_purchase_check():
    b = BO3(beta=0.15)
    black, white = np.array([10.0, 0, 0]), np.array([95.0, 0, 0])
    r_same = b.purchase_check(E[0], "Knitwear", E[:1], ["Knitwear"], black, np.array([black]))
    r_diff = b.purchase_check(E[0], "Knitwear", E[:1], ["Knitwear"], white, np.array([black]))
    assert r_same["verdict"] == "DOUBLON" and r_diff["verdict"] != "DOUBLON" and r_diff["similarity"] < r_same["similarity"]


def test_diagnose_colour_lists_worst_variants_sorted():
    import importlib.util, numpy as np
    from PIL import Image
    spec = importlib.util.spec_from_file_location("diagnose_colour", Path(__file__).resolve().parents[1] / "diagnose_colour.py")
    dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)
    rng = np.random.default_rng(3)
    imgs = [Image.fromarray(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)).resize((96, 96)) for _ in range(30)]
    w = dc.worst_variants(imgs, n_aug=20, top=5)
    assert len(w) == 5 and all(w[k][1] >= w[k + 1][1] for k in range(4))


def _garment_on(bg, fill, box=(30, 20, 90, 84), size=128):
    from PIL import Image
    im = Image.new("RGB", (size, size), bg); p = im.load()
    for x0 in range(box[0], box[2]):
        for y0 in range(box[1], box[3]): p[x0, y0] = fill
    return im


def test_colour_is_independent_of_the_background_grey():
    """Meme pantalon noir sur fond blanc, gris clair et gris : meme couleur (l'ancienne lecture comptait le fond gris comme vetement)."""
    from bo3.bo3_service import colour_lab
    labs = [colour_lab(_garment_on(bg, (20, 20, 20))) for bg in ((255, 255, 255), (232, 232, 234), (205, 206, 210))]
    assert all(l[0] < 20 for l in labs)
    assert max(np.linalg.norm(labs[0] - l) for l in labs) < 8


def test_black_and_blue_tshirts_differ_clearly_and_two_blacks_do_not():
    from bo3.bo3_service import colour_lab
    black_grey = colour_lab(_garment_on((226, 227, 230), (25, 25, 28)))
    black_white = colour_lab(_garment_on((255, 255, 255), (22, 22, 22)))
    blue_white = colour_lab(_garment_on((255, 255, 255), (60, 90, 160)))
    navy_grey = colour_lab(_garment_on((226, 227, 230), (25, 30, 70)))
    assert np.linalg.norm(black_grey - black_white) < 10
    assert np.linalg.norm(blue_white - navy_grey) > 25
    assert np.linalg.norm(blue_white - black_white) > 30


def test_check_colours_agreement_helper():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_colours", Path(__file__).resolve().parents[1] / "check_colours.py")
    cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)
    from bo3.bo3_service import rgb2lab
    labs = np.array([rgb2lab(np.array(rgb) / 255.0) for rgb in ((20, 20, 20), (60, 90, 160), (245, 245, 245))])
    rows = cc.agreement(labs, ["black", "blue", None])
    assert rows == [(0, "black", "black"), (1, "blue", "blue")]
