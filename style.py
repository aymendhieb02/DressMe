"""User Style Classification : profil de style (Casual, Sporty, Formal, Ethnic) à partir de photos d'articles (CNN)."""
import io, json, os, threading
from functools import lru_cache
from pathlib import Path
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel

from engine import UserState
from reco import eng, card, RDIR

DATA = Path(os.environ.get("DRESSME_DATA", "data"))
SDIR = DATA / "style"                      # dress_me_style.onnx + class_names_v2.json
router = APIRouter(prefix="/api/style", tags=["style"])
IMG_SIZE = (224, 224)
MAX_FILES, MAX_MB = 12, 8
USAGE_TO_STYLE = {"Casual": "Casual", "Sports": "Sporty", "Formal": "Formal", "Ethnic": "Ethnic"}
LOCK = threading.Lock()


@lru_cache(1)
def model():
    import onnxruntime as ort
    names = json.load(open(SDIR / "class_names_v2.json", encoding="utf-8"))
    sess = ort.InferenceSession(str(SDIR / "dress_me_style.onnx"), providers=["CPUExecutionProvider"])
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
    items: list[int] = []
    gender: str = "all"


@router.post("/likes")
def from_likes(b: LIn):
    e = eng(); N = len(e.cat)
    ids = [int(i) for i in dict.fromkeys(b.items) if 0 <= i < N][:MAX_FILES]
    if not ids:
        raise HTTPException(400, "Like at least one piece in Taste Studio first")
    arrs, imgs = [], []
    for i in ids:
        p = RDIR / "thumbs" / f"{int(e.cat.at[i, 'id'])}.jpg"
        if p.exists():
            arrs.append(prep(Image.open(p))); imgs.append(f"/reco_img/{p.name}")
    if not arrs:
        raise HTTPException(404, "Thumbnails not found")
    ps, pt = predict(arrs)
    r = build(ps, pt, [f"piece {k + 1}" for k in range(len(arrs))], imgs)
    r["recs"] = recommend(r["dominant"], b.gender, ids)
    return r


@router.post("/photos")
def from_photos(files: list[UploadFile] = File(...), gender: str = Form("all")):
    if not files:
        raise HTTPException(400, "Add at least one photo")
    arrs, labels = [], []
    for f in files[:MAX_FILES]:
        raw = f.file.read()
        if len(raw) > MAX_MB * 1e6:
            raise HTTPException(400, f"{f.filename} is larger than {MAX_MB} MB")
        try:
            arrs.append(prep(Image.open(io.BytesIO(raw)))); labels.append(f.filename or "photo")
        except Exception:
            raise HTTPException(400, f"{f.filename} is not a valid image")
    ps, pt = predict(arrs)
    r = build(ps, pt, labels)
    r["recs"] = recommend(r["dominant"], gender)
    return r