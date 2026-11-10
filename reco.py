"""Account-scoped Taste Studio over the Myntra recommendation catalog."""
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user, current_user_csrf
from app.database import get_db
from app.models import TasteReaction, User
from engine import Engine, UserState, STYLES

DATA = Path(os.environ.get("DRESSME_DATA", Path(__file__).resolve().parent / "data"))
RDIR = DATA / "reco"
router = APIRouter(prefix="/api/reco", tags=["taste"])
SLOTS = {"haut", "bas", "robe", "veste", "chaussures", "sac", "montre", "bijou", "accessoire"}
LOCK = threading.Lock()


@lru_cache(1)
def eng():
    catalog = pd.read_csv(RDIR / "catalog_app.csv")
    e = Engine(catalog, np.load(RDIR / "emb_app.npy"), seed=0)
    if len(e.E) != len(catalog) or catalog["id"].duplicated().any():
        raise RuntimeError("Taste catalog and embeddings are inconsistent")
    e.id_to_index = {int(item_id): i for i, item_id in enumerate(catalog["id"])}
    return e


class FeedIn(BaseModel):
    gender: Literal["all", "Men", "Women"] = "all"
    slot: str | None = None
    n: int = Field(default=12, ge=1, le=24)
    same: bool = True


class ReactionIn(BaseModel):
    item_id: int
    kind: Literal["like", "dislike", "save"]


class SeenIn(BaseModel):
    item_ids: list[int] = Field(max_length=24)


def rows(db: Session, user: User) -> list[TasteReaction]:
    return list(db.scalars(select(TasteReaction).where(TasteReaction.user_id == user.id).order_by(TasteReaction.id)))


def state(db: Session, user: User, gender: str = "all") -> UserState:
    e = eng()
    reactions = rows(db, user)
    indices = [(e.id_to_index.get(r.item_id), r.reaction) for r in reactions]
    u = UserState(gender=gender)
    u.liked = [i for i, kind in indices if i is not None and kind in ("like", "save")][-50:]
    u.disliked = [i for i, kind in indices if i is not None and kind == "dislike"][-50:]
    u.seen = {i for i, _ in indices if i is not None}
    return u


def txt(value):
    return "" if pd.isna(value) else str(value)


def card(index: int):
    row = eng().cat.iloc[int(index)]
    item_id = int(row["id"])
    return dict(id=item_id, name=txt(row["name"]), type=txt(row["articleType"]),
                colour=txt(row["baseColour"]), slot=txt(row["slot"]),
                img=f"/reco_img/{item_id}.jpg")


@router.get("/state")
def get_state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    reactions = rows(db, user)
    return {
        "gender": {"men": "Men", "women": "Women"}.get(user.gender, "all"),
        "liked": [r.item_id for r in reactions if r.reaction in ("like", "save")],
        "disliked": [r.item_id for r in reactions if r.reaction == "dislike"],
        "saved": [card(eng().id_to_index[r.item_id]) for r in reactions
                  if r.reaction == "save" and r.item_id in eng().id_to_index],
        "seen": [r.item_id for r in reactions],
    }


@router.post("/reaction")
def react(body: ReactionIn, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    if body.item_id not in eng().id_to_index:
        raise HTTPException(404, "Taste item not found")
    existing = db.scalar(select(TasteReaction).where(TasteReaction.user_id == user.id,
                                                    TasteReaction.item_id == body.item_id))
    if existing:
        existing.reaction = body.kind
    else:
        db.add(TasteReaction(user_id=user.id, item_id=body.item_id, reaction=body.kind))
    db.commit()
    return {"item_id": body.item_id, "kind": body.kind}


@router.post("/seen")
def mark_seen(body: SeenIn, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    valid = set(eng().id_to_index)
    if any(item_id not in valid for item_id in body.item_ids):
        raise HTTPException(404, "Taste item not found")
    known = {r.item_id for r in rows(db, user)}
    for item_id in dict.fromkeys(body.item_ids):
        if item_id not in known:
            db.add(TasteReaction(user_id=user.id, item_id=item_id, reaction="seen"))
    db.commit()
    return {"seen": len(body.item_ids)}


@router.delete("/state")
def clear_state(user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    db.execute(delete(TasteReaction).where(TasteReaction.user_id == user.id))
    db.commit()
    return {"cleared": True}


@router.post("/feed")
def feed(body: FeedIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with LOCK:
        e, u = eng(), state(db, user, body.gender)
        return {"items": [card(i) for i in e.recommend(u, n=body.n,
                                                       slot=body.slot if body.slot in SLOTS else None)]}


@router.post("/foryou")
def foryou(body: FeedIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with LOCK:
        e, u = eng(), state(db, user, body.gender)
        if len(u.liked) < 3:
            return {"ready": False, "need": 3 - len(u.liked), "items": [], "styles": []}
        profile = e.P[u.liked].mean(0)
        if u.disliked:
            profile -= 0.6 * e.P[u.disliked].mean(0)
        top = np.argsort(-profile)[:2]
        ok = e.allowed(u)
        ok[list(u.seen)] = False
        if body.slot in SLOTS:
            ok &= e.slot == body.slot
        scores = e.scores(u)
        candidates = np.where(ok & np.isin(e.top1, top))[0] if body.same else np.where(ok)[0]
        if candidates.size < 6:
            candidates = np.where(ok)[0]
        pool = candidates[np.argsort(-scores[candidates])[:150]]
        picked = e._mmr(pool, scores[pool], body.n, 0.15) if pool.size else []
        items = []
        for i in picked:
            liked_index = u.liked[int(np.argmax(e.E[i] @ e.E[u.liked].T))]
            items.append(dict(card(i), because={"id": int(e.cat.at[liked_index, "id"]),
                                                "name": txt(e.cat.at[liked_index, "name"])}))
        return {"ready": True, "styles": [STYLES[i] for i in top], "items": items}


@router.post("/profile")
def profile(body: FeedIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e, u = eng(), state(db, user, body.gender)
    if len(u.liked) < 5:
        return {"ready": False, "need": 5 - len(u.liked)}
    values = e.P[u.liked].mean(0)
    return {"ready": True, "styles": sorted(
        [{"style": style, "share": float(value)} for style, value in zip(STYLES, values)],
        key=lambda entry: -entry["share"])}
