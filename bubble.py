"""Bubble Breaker: blend familiar matches with less explored Taste styles."""
import numpy as np
from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user
from app.database import get_db
from app.models import User
from engine import STYLES
from reco import FeedIn, LOCK, card, eng, state

router = APIRouter(prefix="/api/bubble", tags=["taste"])


class BubbleIn(FeedIn):
    alpha: float = Field(default=0.25, ge=0, le=1)


def normalize(values):
    low, high = float(values.min()), float(values.max())
    return (values - low) / (high - low) if high > low else np.zeros_like(values)


@router.post("/recommendations")
def recommendations(body: BubbleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with LOCK:
        e, u = eng(), state(db, user, body.gender)
        if len(u.liked) < 3:
            return {"ready": False, "need": 3 - len(u.liked), "items": [], "alpha": body.alpha}
        allowed = e.allowed(u)
        allowed[list(u.seen)] = False
        if body.slot:
            allowed &= e.slot == body.slot
        candidates = np.where(allowed)[0]
        if not candidates.size:
            return {"ready": True, "items": [], "alpha": body.alpha}

        relevance = e.scores(u)[candidates]
        counts = np.bincount(e.top1[u.liked], minlength=len(STYLES))
        surprise = -np.log((counts[e.top1[candidates]] + 1) / (len(u.liked) + len(STYLES)))
        combined = (1 - body.alpha) * normalize(relevance) + body.alpha * normalize(surprise)
        pool_indices = np.argsort(-combined)[:200]
        pool = candidates[pool_indices]
        picks = e._mmr(pool, combined[pool_indices], body.n, 0.12)
        items = [dict(card(i), style=STYLES[e.top1[i]],
                      reason=f"Explore {STYLES[e.top1[i]]} beyond your usual picks") for i in picks]
        return {"ready": True, "items": items, "alpha": body.alpha}
