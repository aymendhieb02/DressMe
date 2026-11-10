"""Real garments inside the catalog-based wardrobe, as a per-request overlay.

wardrobe.py identifies every piece by its position in the shared catalog arrays. A user's
own garments are not in those arrays and must not be added to them, so each request builds
an OwnedCatalog: the catalog plus that user's pieces. Nothing global is changed, so one
user's garments cannot reach another request, and the shared files stay untouched.

Inside a request a piece has a dense position (len(catalog) + k). Outside, it has a stable
public id (PUBLIC_ID_BASE + seq) that the catalog cannot reach.
"""
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

import numpy as np
import torch
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.garments.taxonomy import new_item_code, wardrobe_fields
from app.models import Garment, GarmentWardrobeProfile
from app.storage.local_disk import LocalPrivateStorage

PUBLIC_ID_BASE = 1_000_000
EMBEDDING_MODEL = "ViT-B-32/laion2b_s34b_b79k"
EMBEDDING_DIM = 512
OWNED_ROW_LIMIT = 8


def enabled() -> bool:
    return get_settings().bo6_enabled


@dataclass(frozen=True)
class OwnedPiece:
    public_id: int
    code: str
    category: str
    description: str
    garment_id: UUID
    vector: np.ndarray | None

    def as_item(self) -> dict:
        return dict(i=self.public_id, c=self.category, d=self.description, k=self.code, owned=True,
                    photo=f"/studio-api/garments/{self.garment_id}/image")


def _refresh_embedding(row: Garment, encode) -> bool:
    """Compute the vector with the team's encoder, once. Returns True when the row changed."""
    profile = row.profile
    if profile.embedding_status == "ready" and profile.embedding_model == EMBEDDING_MODEL:
        return False
    if profile.embedding_status == "failed" and profile.embedding_model == EMBEDDING_MODEL:
        return False
    profile.embedding_model = EMBEDDING_MODEL
    try:
        vector = np.asarray(encode(LocalPrivateStorage().read(row.image_key)), dtype=np.float32)
        if vector.shape != (EMBEDDING_DIM,):
            raise ValueError("unexpected embedding shape")
    except Exception as error:  # the garment stays listed; it is only left out of scoring
        print(f"[wardrobe_owned] embedding failed for garment {row.id}: {type(error).__name__}")
        profile.clip_embedding, profile.embedding_status = None, "failed"
        return True
    profile.clip_embedding, profile.embedding_status = vector.tobytes(), "ready"
    return True


def _piece(row: Garment) -> OwnedPiece:
    profile = row.profile
    ready = profile.embedding_status == "ready" and profile.embedding_model == EMBEDDING_MODEL
    vector = np.frombuffer(profile.clip_embedding, dtype=np.float32) if ready and profile.clip_embedding else None
    return OwnedPiece(PUBLIC_ID_BASE + profile.seq, profile.item_code, profile.outfit_cat,
                      row.description.rstrip("."), row.id, vector)


def load_owned(user_id: UUID, encode=None) -> list[OwnedPiece]:
    """This user's garments, oldest first. With encode, missing embeddings are computed and stored."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(Garment).where(Garment.user_id == user_id).order_by(Garment.created_at, Garment.id)
        ).all()
        changed = False
        for row in rows:
            if row.profile is None:  # saved before the integration
                row.profile = GarmentWardrobeProfile(user_id=row.user_id, item_code=new_item_code(),
                                                     **wardrobe_fields(row.category))
                changed = True
            if encode is not None:
                changed = _refresh_embedding(row, encode) or changed
        if changed:
            try:
                db.commit()
            except IntegrityError:  # a concurrent request stored the same profile first
                db.rollback()
                return load_owned(user_id)
        return [_piece(row) for row in rows]


class _OverlayScoring:
    def __init__(self, scoring, embeddings: torch.Tensor):
        self._scoring = scoring
        self._embeddings = embeddings

    def score_outfits(self, outfits):
        return self._scoring.score_outfits(outfits, E=self._embeddings)


class OwnedCatalog:
    """Stands in for the catalog parameter `a` that every wardrobe.py helper receives."""

    def __init__(self, catalog, pieces: list[OwnedPiece]):
        self._catalog = catalog
        self.pieces = pieces
        self.catalog_size = len(catalog.CAT)
        vectors = np.stack([piece.vector for piece in pieces])
        self.CAT = np.concatenate([np.asarray(catalog.CAT), np.array([piece.category for piece in pieces])])
        self.EMB = np.vstack([catalog.EMB, vectors])
        self.BYCAT = catalog.BYCAT  # recommendation candidates stay catalog-only
        self.local_ids = list(range(self.catalog_size, self.catalog_size + len(pieces)))
        scored = torch.cat([catalog.scoring._S["E"], torch.from_numpy(vectors.copy()).float()])
        self.scoring = _OverlayScoring(catalog.scoring, scored)

    def __getattr__(self, name):
        return getattr(self._catalog, name)

    def it(self, i: int) -> dict:
        i = int(i)
        return self._catalog.it(i) if i < self.catalog_size else self.pieces[i - self.catalog_size].as_item()

    def catalog_ids(self, items) -> list[int]:
        return [i for i in items if i < self.catalog_size]

    def mark_looks(self, looks: list[dict]) -> list[dict]:
        """Lists each look's owned pieces and returns the "You own" row, most used first."""
        uses = Counter()
        by_id = {piece.public_id: piece for piece in self.pieces}
        for look in looks:
            look["owned"] = [item["i"] for item in look["items"] if item.get("owned")]
            uses.update(look["owned"])
        row = []
        for public_id, count in uses.most_common(OWNED_ROW_LIMIT):
            item = by_id[public_id].as_item()
            row.append(dict(i=item["i"], d=item["d"], photo=item["photo"], looks=count))
        return row


def overlay_for(catalog, user_id: UUID, *, men: bool, encode) -> OwnedCatalog | None:
    """None when this user has nothing to score, so the caller takes today's exact path."""
    pieces = [
        piece for piece in load_owned(user_id, encode)
        if piece.vector is not None and piece.category != "other" and not (men and piece.category == "dress")
    ]
    return OwnedCatalog(catalog, pieces) if pieces else None
