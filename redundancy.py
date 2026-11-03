"""BO3 : redondance dans la garde-robe (quasi-doublons, score d'encombrement, concentration de couleurs, alerte avant achat).

Meme principe que similar.py et wardrobe.py : un routeur branche dans api.py.
Entrees : indices du catalogue (comme /api/wardrobe/complete). Sorties : voir /api/redundancy/analyse.
"""
import os, random
from functools import lru_cache
from pathlib import Path
import itertools, json
import numpy as np, pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from bo3.bo3_service import BO3

DATA = Path(os.environ.get("DRESSME_DATA", "data"))
router = APIRouter(prefix="/api/redundancy", tags=["redundancy"])

T_DUP_FALLBACK = 0.92      # meme coupure que wardrobe.py (pas de quasi-doublons dans les candidats)
PALETTE = ["black", "white", "grey", "beige", "brown", "blue", "burgundy", "pink", "red", "green"]
ALIAS = {"navy": "blue"}   # "navy" et "dark blue" -> "blue" (1 article chacun dans le catalogue)
MAX_ITEMS = 200
EXAMPLE_SIZE = 32    # >= 30 pieces : le score d'encombrement (valide vers 40 pieces) et la carte des couleurs (>= 30) n'affichent plus d'avertissement

# Les categories de l'appli sont larges (bottom = pantalons + jupes + shorts). Pour ne comparer que des pieces de meme nature,
# on affine avec la description : "bottom/Skirts", "top/T-shirts"... (ordre = priorite : "t-shirt" avant "shirt").
TYPE_KW = {
    "bottom": [("skirt", "Skirts"), ("shorts", "Shorts"), ("jeans", "Jeans"), ("pants", "Pants"), ("trousers", "Pants")],
    "top": [("t-shirt", "T-shirts"), ("henley", "T-shirts"), ("polo", "Polos"), ("cardigan", "Knitwear"), ("sweater", "Knitwear"),
            ("turtleneck", "Knitwear"), ("vest", "Knitwear"), ("shirt", "Shirts"), ("blouse", "Shirts"), ("tank", "Tops")],
    "outer": [("blazer", "Blazers"), ("coat", "Coats"), ("jacket", "Jackets"), ("blouson", "Jackets"), ("hoodie", "Jackets")],
    "shoes": [("sneaker", "Sneakers"), ("loafer", "Loafers"), ("moccasin", "Loafers"), ("derby", "Loafers"), ("boot", "Boots"),
              ("sandal", "Sandals"), ("slide", "Sandals"), ("espadrille", "Sandals"), ("pump", "Heels"), ("mule", "Heels"),
              ("slingback", "Heels"), ("wedge", "Heels")],
    "bag": [("bag", "Bags"), ("clutch", "Bags"), ("backpack", "Bags")],
}

def type_of(group, desc):
    d = desc.lower()
    for k, label in TYPE_KW.get(group, []):
        if k in d: return f"{group}/{label}"
    return group               # pas de sous-type reconnu : on garde la categorie large

group_of = lambda cat: cat.split("/")[0]
label_of = lambda cat: cat.split("/")[1] if "/" in cat else cat

def A():                   # import tardif : evite l'import circulaire avec api.py
    import api
    return api

@lru_cache(1)
def embs():
    """Embeddings du moteur : data/emb_bo3.npy (ecrit par calibrate_bo3.py quand emb_clip.npy ne correspond pas au pipeline CLIP recalcule), sinon emb_clip.npy."""
    f = DATA / "bo3_emb.npy"
    if f.exists(): return np.load(f)
    return np.asarray(A().EMB)

@lru_cache(1)
def labs():
    """Couleurs Lab (lues sur les pixels) de tout le catalogue : data/bo3_colour_lab.npy, ecrit par calibrate_bo3.py. None si absent."""
    f = DATA / "bo3_colour_lab.npy"
    return np.load(f) if f.exists() else None

@lru_cache(1)
def types():
    a = A(); return [type_of(g, d) for g, d in zip(a.CAT, a.DESC)]

def bytype():
    out = {}
    for i, t in enumerate(types()): out.setdefault(t, []).append(i)
    return out

def colour_of(desc):
    w = desc.lower().replace("dark blue", "blue").split()
    c = ALIAS.get(w[0], w[0]) if w else None
    return c if c in PALETTE else None      # "neutral", "multicoloured"... -> pas de couleur

@lru_cache(1)
def engine():
    """Moteur BO3 regle pour le catalogue de l'appli (embeddings CLIP, 7 categories)."""
    a = A(); E = np.asarray(embs(), dtype=np.float32); E = E / np.clip(np.linalg.norm(E, axis=1, keepdims=True), 1e-12, None)
    f = DATA / "bo3_thresholds.json"
    mdl = "clip"; beta = 0.0; tau = None
    if f.exists():
        th = json.loads(f.read_text()); mdl = th.get("model", "clip"); beta = float(th.get("beta", 0.0)) if labs() is not None else 0.0; tau = th.get("colour_tau") if labs() is not None else None; t_dup, t_sim, src = th["T_DUP"], th["T_SIM"], th.get("source", "calibrated on this catalogue")
        t_grise = th.get("T_GRISE")                    # absent : le moteur le place a la meme position relative que dans l'etude (provisoire)
    else:                                    # provisoire : 99e percentile des paires de meme type
        sims = [float(x) for idx in bytype().values() if len(idx) > 1 for x in (lambda S: S[np.triu_indices(len(S), 1)])(E[idx] @ E[idx].T)]
        t_sim = float(np.percentile(sims, 99)); t_dup = max(T_DUP_FALLBACK, t_sim + 0.02)
        src = "provisional: run bo3/calibrate_bo3.py to calibrate them on this catalogue"; t_grise = None
    group_of_ = group_of; cols = [colour_of(d) for d in a.DESC]; groups = list(getattr(a, "CATS", ["shoes", "bag", "dress", "outer", "top", "bottom", "other"]))
    cnt = pd.DataFrame(0.5, index=groups, columns=PALETTE)    # lissage : aucune case a probabilite nulle
    for g, c in zip(a.CAT, cols):
        if c and g in cnt.index: cnt.loc[g, c] += 1
    ref = cnt / cnt.values.sum()
    return BO3(data_dir=Path(__file__).parent / "bo3" / "data", t_dup=t_dup, t_sim=t_sim, t_grise=t_grise, beta=beta, reference=ref,
               group_of=lambda c: group_of_(c) if group_of_(c) in groups else None, threshold_source=src, model=mdl, colour_tau=tau)

def same_colour(cols):
    """True si toutes les pieces ont la meme couleur, False si elles different, None si une couleur est inconnue."""
    if any(c is None for c in cols): return None
    return len(set(cols)) == 1

def group_same_colour(ids, a):
    """Meme couleur ? Sur les pixels (ecart de couleur max du groupe < colour_tau) quand ils sont disponibles ; sinon d'apres la description."""
    L, tau = labs(), engine().colour_tau
    if tau and L is not None:
        return bool(max(float(np.linalg.norm(L[x] - L[y])) for x, y in itertools.combinations(ids, 2)) < tau)
    return same_colour([colour_of(a.DESC[i]) for i in ids])

def _item(a, i):
    d = dict(item_id=int(i), category=types()[i], colour=colour_of(a.DESC[i]), embedding=embs()[i])
    if (engine().beta > 0 or engine().colour_tau) and labs() is not None: d["lab"] = labs()[i]      # couleur lue sur les pixels : fusion (beta > 0) et/ou regle de couleur
    return d

@lru_cache(1)
def sim_matrix():
    """Similarite de tout le catalogue, avec la meme fusion couleur que le moteur (pour l'exemple et find_pairs)."""
    E = np.asarray(embs(), dtype=np.float32); E = E / np.clip(np.linalg.norm(E, axis=1, keepdims=True), 1e-12, None)
    return engine().fuse(E @ E.T, labs())

def _clean(o):
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    return o

class Answer(BaseModel):
    a: int                 # indices du catalogue des deux pieces de la question
    b: int
    redundant: bool        # reponse de l'utilisatrice a « Do you consider these two pieces redundant? »

class In(BaseModel):
    items: list[int]
    candidate: int | None = None
    answers: list[Answer] = []

@router.post("/analyse")
def analyse(b: In):
    a = A(); n = len(a.CODES); ids = list(dict.fromkeys(b.items))
    if not ids: raise HTTPException(400, "Add at least 1 piece to your wardrobe")
    if len(ids) > MAX_ITEMS: raise HTTPException(400, f"Too many pieces (max {MAX_ITEMS})")
    if any(i < 0 or i >= n for i in ids + ([b.candidate] if b.candidate is not None else [])): raise HTTPException(400, "Unknown item")
    if b.candidate in ids: raise HTTPException(400, "This piece is already in your wardrobe")
    r = engine().analyse_wardrobe([_item(a, i) for i in ids], candidate=_item(a, b.candidate) if b.candidate is not None else None,
                                  answers=[x.model_dump() for x in b.answers])
    for g in r["duplicate_groups"]:
        ids_g = g.pop("item_ids"); g["items"] = [a.it(i) for i in ids_g]
        g["same_colour"] = group_same_colour(ids_g, a); g["category"] = label_of(g["category"])
    for c in r["clutter"]["by_category"]: c["category"] = label_of(c["category"])
    for q in r["to_confirm"]:                                  # paires de la zone grise : pieces completes pour l'affichage
        q["items"] = [a.it(i) for i in q.pop("item_ids")]; q["category"] = label_of(q["category"])
    for c in r["colour_map"]["flagged"]: c["category"] = c.pop("group")
    for c in r["colour_map"].get("cells", []): c["category"] = c.pop("group")
    p = r["purchase_check"]
    if p and p.get("nearest_item_id") is not None: p["nearest"] = a.it(p["nearest_item_id"])
    return _clean(r)

@router.get("/example")
def example():
    """Garde-robe de demonstration : les paires les plus proches du catalogue + des pieces variees (>= 20 pieces)."""
    a = A(); SM = sim_matrix()
    pairs = []
    for t, idx in bytype().items():
        if t == "other" or len(idx) < 2: continue
        S = SM[np.ix_(idx, idx)]
        for x, y in zip(*np.triu_indices(len(idx), 1)): pairs.append((float(S[x, y]), idx[x], idx[y]))
    pairs.sort(reverse=True); pick = []
    for s, i, j in pairs:
        if len(pick) >= 8: break
        if i not in pick and j not in pick: pick += [i, j]
    cols = [colour_of(d) for d in a.DESC]                    # une concentration de couleur reelle : la case (categorie, couleur) la plus fournie du catalogue
    cell = {}
    for i, (g, c) in enumerate(zip(a.CAT, cols)):
        if c and g != "other" and i not in pick: cell.setdefault((g, c), []).append(i)
    if cell: pick += random.sample(max(cell.values(), key=len), min(10, len(max(cell.values(), key=len))))
    rest = [i for i in range(len(a.CODES)) if i not in pick and a.CAT[i] != "other"]
    random.shuffle(rest); pick += rest[:max(0, EXAMPLE_SIZE - len(pick))]
    random.shuffle(pick)
    return dict(items=[a.it(i) for i in pick])
