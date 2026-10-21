"""Wardrobe Completion : recommande les pièces qui maximisent le nombre de nouvelles tenues."""
import itertools, random
import numpy as np, torch
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/wardrobe", tags=["wardrobe"])
TEMPLATES = [("top", "bottom", "shoes"), ("dress", "shoes")]   # tenues de base
THR = 7.0                                                      # score mini pour qu'une tenue soit "valide"

def A():                       # import tardif : évite l'import circulaire avec api.py
    import api
    return api

class WIn(BaseModel):
    items: list[int]
    n: int = 3
    thr: float = THR

def outfits(a, W, must=None):
    """Toutes les tenues possibles avec la garde-robe W : base + (rien | 1 veste | 1 sac). Max 4 pièces."""
    by = {}
    for i in W: by.setdefault(a.CAT[i], []).append(i)
    res = []
    for t in TEMPLATES:
        pools = [by.get(c, []) for c in t]
        if not all(pools): continue
        layers = [()] + [(o,) for o in by.get("outer", [])] + [(b,) for b in by.get("bag", [])]
        for base in itertools.product(*pools):
            for ly in layers:
                r = base + ly
                if must is None or must in r: res.append(r)
    return res

def score_outfits(a, outs):
    if not outs: return np.zeros(0)
    res = np.zeros(len(outs)); groups = {}
    for j, o in enumerate(outs): groups.setdefault(len(o), []).append(j)
    with torch.no_grad():
        for L, js in groups.items():
            for s in range(0, len(js), 512):
                ch = js[s:s + 512]
                x = torch.tensor(a.EMB_FT[[list(outs[j]) for j in ch]]).float()
                sc, _ = a.SC(x, torch.ones(len(ch), L, dtype=torch.bool))
                res[ch] = sc.numpy()
    return res

def pool(a, cur, per=20, extra=8):
    """Candidats : les plus proches du style du dressing + quelques-uns au hasard (diversité)."""
    E = a.EMB; m = E[cur].mean(0); m = m / (np.linalg.norm(m) + 1e-9)
    have, out, rng = set(cur), [], random.Random(len(cur))
    for c in ("top", "bottom", "dress", "shoes", "outer", "bag"):
        idx = [i for i in a.BYCAT.get(c, []) if i not in have]
        if not idx: continue
        order = np.argsort(-(E[idx] @ m)); keep = [idx[j] for j in order[:per]]
        rest = [idx[j] for j in order[per:]]; keep += rng.sample(rest, min(extra, len(rest)))
        own = [i for i in cur if a.CAT[i] == c]
        if own: keep = [i for i in keep if float((E[own] @ E[i]).max()) < 0.92]   # pas de quasi-doublons
        out += keep
    return out

@router.get("/sample")
def sample():
    a = A(); ids = []
    for o in random.sample(a.TEST, min(3, len(a.TEST))):
        for i in o["items"]:
            if i not in ids and a.CAT[i] != "other": ids.append(i)
    return dict(items=[a.it(i) for i in ids[:12]])

@router.post("/complete")
def complete(b: WIn):
    a = A(); cur = list(dict.fromkeys(b.items))
    if len(cur) < 3: raise HTTPException(400, "Add at least 3 pieces to your wardrobe")
    n = max(1, min(b.n, 5))
    o0 = outfits(a, cur); before = int((score_outfits(a, o0) >= b.thr).sum())
    recs = []
    for _ in range(n):
        best = None
        for c in pool(a, cur):
            outs = outfits(a, cur + [c], must=c)
            if not outs: continue
            sc = score_outfits(a, outs); gain = int((sc >= b.thr).sum())
            key = (gain, float(sc.mean()))
            if best is None or key > best[0]: best = (key, c, outs, sc)
        if best is None:      # il manque une catégorie de base : on la complète d'abord
            miss = next((c for c in ("bottom", "top", "shoes") if not any(a.CAT[i] == c for i in cur)), None)
            cands = [i for i in pool(a, cur) if a.CAT[i] == miss] if miss else []
            if not cands: break
            recs.append(dict(item=a.it(cands[0]), gain=0, best_score=None, look=[])); cur.append(cands[0]); continue
        (gain, _), c, outs, sc = best; j = int(sc.argmax())
        recs.append(dict(item=a.it(c), gain=gain, best_score=float(sc[j]), look=[a.it(i) for i in outs[j]]))
        cur.append(c)
    o1 = outfits(a, cur); after = int((score_outfits(a, o1) >= b.thr).sum())
    return dict(recs=recs, before=before, after=after)