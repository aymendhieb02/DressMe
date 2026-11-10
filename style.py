"""User Style Classification : profil de style (Casual, Sporty, Formal, Ethnic) à partir de photos d'articles (CNN)."""
import io, json, os, threading
from functools import lru_cache
from pathlib import Path
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user, current_user_csrf
from app.database import get_db
from app.models import User
from engine import UserState
from reco import eng, card, RDIR, state as taste_state, LOCK as RECO_LOCK

DATA = Path(os.environ.get("DRESSME_DATA", Path(__file__).resolve().parent / "data"))
SDIR = DATA / "style"                      # dress_me_style.onnx + class_names_v2.json
router = APIRouter(prefix="/api/style", tags=["style"])
IMG_SIZE = (224, 224)
MAX_FILES, MAX_MB = 12, 8
USAGE_TO_STYLE = {"Casual": "Casual", "Sports": "Sporty", "Formal": "Formal", "Ethnic": "Ethnic"}
LOCK = threading.Lock()


@lru_cache(1)
def model():
    import onnxruntime as ort
    with open(SDIR / "class_names_v2.json", encoding="utf-8") as names_file:
        names = json.load(names_file)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(SDIR / "dress_me_style.onnx"), sess_options=options,
                                providers=["CPUExecutionProvider"])
    return sess, names["styles"], names["types"]


def prep(img):
    # même prétraitement que l'entraînement : RGB, 224x224, pixels bruts 0-255 (EfficientNet normalise en interne)
    return np.asarray(img.convert("RGB").resize(IMG_SIZE, Image.BILINEAR), np.float32)


def predict(arrs):
    sess, S, T = model()
    X = np.stack(arrs).astype(np.float32)
    with LOCK:
        outs = sess.run(None, {sess.get_inputs()[0].name: X})
    ps = next(o for o in outs if o.shape[1] == len(S))
    pt = next(o for o in outs if o.shape[1] == len(T))
    return ps, pt


def build(ps, pt, labels, imgs=None):
    _, S, T = model()
    prof = ps.mean(0); order = np.argsort(-prof)
    items = []
    for k in range(len(ps)):
        it = dict(label=labels[k], type=T[int(pt[k].argmax())], type_conf=float(pt[k].max()),
                  style=S[int(ps[k].argmax())], style_conf=float(ps[k].max()))
        if imgs: it["img"] = imgs[k]
        items.append(it)
    return dict(profile=[dict(style=S[j], share=float(prof[j])) for j in order],
                dominant=S[int(order[0])], dominant_share=float(prof[order[0]]), items=items)


def recommend(style, gender, liked=None, n=12):
    with RECO_LOCK:
        e = eng()
        u = UserState(gender=gender if gender in ("Men", "Women") else "all", liked=list(liked or []))
        ok = e.cat["usage"].map(USAGE_TO_STYLE).eq(style).to_numpy() & e.allowed(u)
        ok[u.liked] = False
        idx = np.where(ok)[0]
        if not idx.size:
            return []
        if u.liked:
            sc = e.scores(u); pool = idx[np.argsort(-sc[idx])[:150]]
            picks = e._mmr(pool, sc[pool], min(n, pool.size), 0.3)
        else:
            picks = e.rng.choice(idx, min(n, idx.size), replace=False).tolist()
        return [card(i) for i in picks]


class LIn(BaseModel):
    gender: str = "all"


@router.post("/likes")
def from_likes(b: LIn, user: User = Depends(current_user_csrf), db: Session = Depends(get_db)):
    e = eng()
    ids = taste_state(db, user, b.gender).liked[-MAX_FILES:]
    if not ids:
        raise HTTPException(400, "Like at least one piece in Taste Studio first")
    arrs, imgs = [], []
    for i in ids:
        p = RDIR / "thumbs" / f"{int(e.cat.at[i, 'id'])}.jpg"
        if p.exists():
            with Image.open(p) as image:
                arrs.append(prep(image))
            imgs.append(f"/reco_img/{p.name}")
    if not arrs:
        raise HTTPException(404, "Thumbnails not found")
    ps, pt = predict(arrs)
    r = build(ps, pt, [f"piece {k + 1}" for k in range(len(arrs))], imgs)
    r["recs"] = recommend(r["dominant"], b.gender, ids)
    return r


@router.post("/sample")
def from_sample(b: LIn, _user: User = Depends(current_user_csrf)):
    """A bundled catalog image lets new users try the model without uploading."""
    e = eng()
    gender = b.gender if b.gender in ("Men", "Women") else "Women"
    match = e.cat[(e.cat["gender"] == gender) & (e.cat["slot"].isin(["robe", "haut", "veste"]))]
    if match.empty:
        raise HTTPException(404, "No sample photo is available")
    index = int(match.index[0])
    image_path = RDIR / "thumbs" / f"{int(e.cat.at[index, 'id'])}.jpg"
    with Image.open(image_path) as image:
        pixels = prep(image)
    ps, pt = predict([pixels])
    result = build(ps, pt, ["Catalog sample"], [f"/reco_img/{image_path.name}"])
    result["recs"] = recommend(result["dominant"], b.gender)
    return result


@router.post("/photos")
def from_photos(files: list[UploadFile] = File(...), gender: str = Form("all"),
                _user: User = Depends(current_user_csrf)):
    if not files:
        raise HTTPException(400, "Add at least one photo")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Upload at most {MAX_FILES} photos")
    arrs, labels = [], []
    for f in files:
        if f.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(400, "Photos must be JPG, PNG or WEBP")
        raw = f.file.read(MAX_MB * 1_000_000 + 1)
        if len(raw) > MAX_MB * 1e6:
            raise HTTPException(400, f"{f.filename} is larger than {MAX_MB} MB")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                arrs.append(prep(image))
            labels.append(f.filename or "photo")
        except Exception:
            raise HTTPException(400, f"{f.filename} is not a valid image")
    ps, pt = predict(arrs)
    r = build(ps, pt, labels)
    r["recs"] = recommend(r["dominant"], gender)
    return r
