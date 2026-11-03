"""Taste Studio : apprentissage des goûts par likes / dislikes / favoris (catalogue Myntra) et recommandations."""
import os, threading
from functools import lru_cache
from pathlib import Path
import numpy as np, pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel
from engine import Engine, UserState, STYLES

DATA = Path(os.environ.get("DRESSME_DATA", "data"))
RDIR = DATA / "reco"                       # catalog_app.csv, emb_app.npy, thumbs/
router = APIRouter(prefix="/api/reco", tags=["taste"])
SLOTS = {"haut", "bas", "robe", "veste", "chaussures", "sac", "montre", "bijou", "accessoire"}
LOCK = threading.Lock()                    # le générateur aléatoire du moteur n'est pas thread-safe


@lru_cache(1)
def eng():
    return Engine(pd.read_csv(RDIR / "catalog_app.csv"), np.load(RDIR / "emb_app.npy"), seed=0)


class RIn(BaseModel):
    gender: str = "all"
    liked: list[int] = []
    disliked: list[int] = []
    seen: list[int] = []
    slot: str | None = None
    n: int = 12
    same: bool = True


def state(b):
    N = len(eng().cat)
    keep = lambda L: [int(i) for i in dict.fromkeys(L) if 0 <= i < N]
    u = UserState(gender=b.gender if b.gender in ("Men", "Women") else "all",
                  liked=keep(b.liked), disliked=keep(b.disliked))
    u.seen = set(keep(b.seen)) | set(u.liked) | set(u.disliked)
    return u


def txt(v):
    return "" if pd.isna(v) else str(v)


def card(i):
    r = eng().cat.iloc[int(i)]
    return dict(i=int(i), name=txt(r["name"]), type=txt(r["articleType"]), colour=txt(r["baseColour"]),
                slot=txt(r["slot"]), img=f"/reco_img/{int(r['id'])}.jpg")


@router.post("/feed")
def feed(b: RIn):
    with LOCK:
        e, u = eng(), state(b)
        return dict(items=[card(i) for i in e.recommend(u, n=max(1, min(b.n, 24)), slot=b.slot if b.slot in SLOTS else None)])


@router.post("/foryou")
def foryou(b: RIn):
    with LOCK:
        e, u = eng(), state(b)
        if len(u.liked) < 3:
            return dict(ready=False, need=3 - len(u.liked), items=[], styles=[])
        slot = b.slot if b.slot in SLOTS else None
        prof = e.P[u.liked].mean(0)
        if u.disliked: prof = prof - 0.6 * e.P[u.disliked].mean(0)
        top = np.argsort(-prof)[:2]
        ok = e.allowed(u); ok[list(u.seen)] = False
        if slot: ok &= (e.slot == slot)
        sc = e.scores(u)
        cand = np.where(ok & np.isin(e.top1, top))[0] if b.same else np.where(ok)[0]
        if cand.size < 6: cand = np.where(ok)[0]
        pool = cand[np.argsort(-sc[cand])[:150]]
        recs = e._mmr(pool, sc[pool], max(1, min(b.n, 24)), 0.15) if pool.size else []
        items = []
        for i in recs:
            j = u.liked[int(np.argmax(e.E[i] @ e.E[u.liked].T))]
            items.append(dict(card(i), because=dict(i=j, name=txt(e.cat.at[j, "name"]))))
        return dict(ready=True, styles=[STYLES[s] for s in top], items=items)


@router.post("/profile")
def profile(b: RIn):
    with LOCK:
        e, u = eng(), state(b)
        if len(u.liked) < 5:
            return dict(ready=False, need=5 - len(u.liked))
        p = e.P[u.liked].mean(0)
        return dict(ready=True, styles=sorted([dict(style=s, share=float(v)) for s, v in zip(STYLES, p)], key=lambda x: -x["share"]))