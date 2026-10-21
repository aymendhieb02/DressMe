"""Recherche de similarité + boutiques (SerpAPI Google Lens)."""
import base64, io, json, os
from functools import lru_cache
from pathlib import Path
import numpy as np, requests, torch
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image

DATA = Path(os.environ.get("DRESSME_DATA", "data"))
router = APIRouter(prefix="/api/search", tags=["similarity"])

COLOR_MAPPING = {'Black': 'black', 'White': 'white', 'Red': 'red', 'Blue': 'blue', 'Green': 'green', 'Yellow': 'yellow',
    'Pink': 'pink', 'Purple': 'purple', 'Orange': 'orange', 'Brown': 'brown', 'Beige': 'beige', 'Grey': 'grey',
    'Navy Blue': 'navy', 'Burgundy': 'red', 'Gold': 'gold', 'Silver': 'silver', 'Cream': 'white', 'Khaki': 'beige',
    'Lavender': 'purple', 'Charcoal': 'grey', 'Maroon': 'red', 'Olive': 'green', 'Peach': 'orange', 'Rust': 'brown',
    'Steel': 'grey', 'Multi': 'multi', 'Mustard': 'yellow', 'Teal': 'blue'}
NEUTRAL = {'black', 'grey', 'beige', 'brown', 'navy'}
COMPATIBLE_MIDS = {'pull': ['pull', 'cardigan'], 'tshirt': ['tshirt'], 'shirt': ['shirt', 'blouse'], 'sweat': ['sweat'],
    'dress': ['dress', 'jumpsuit'], 'pants': ['pants'], 'shorts': ['shorts'], 'skirt': ['skirt'], 'sneaker': ['sneaker'],
    'boot': ['boot'], 'heel': ['heel'], 'shoe': ['shoe', 'sneaker', 'loafer'], 'bag': ['bag'], 'jacket': ['jacket'],
    'coat': ['coat'], 'belt': ['belt'], 'hat': ['hat']}

@lru_cache(1)
def store():
    emb = np.load(DATA / "search_emb.npy").astype("float32")
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    return emb, json.load(open(DATA / "search_meta.json"))

@lru_cache(1)
def models():          # chargés au 1er appel seulement (n'alourdit pas le démarrage de l'API)
    import open_clip
    from transformers import AutoImageProcessor, SiglipForImageClassification
    m, _, pre = open_clip.create_model_and_transforms("hf-hub:Marqo/marqo-fashionCLIP")
    name = "prithivMLmods/Fashion-Product-baseColour"
    return m.eval(), pre, AutoImageProcessor.from_pretrained(name), SiglipForImageClassification.from_pretrained(name).eval()

def predict_color(img):
    _, _, cp, cm = models()
    with torch.no_grad():
        p = cm(**cp(images=img, return_tensors="pt")).logits.softmax(-1)
    lab = cm.config.id2label[p.argmax().item()]
    return COLOR_MAPPING.get(lab, lab.lower()), p.max().item()

def attr_set(a): return set(str(a).lower().split(", ")) if a and str(a) != "nan" else set()
def overlap(a, b):
    sa, sb = attr_set(a), attr_set(b)
    return len(sa & sb) / max(len(sa | sb), 1) if sa and sb else 0.0
def color_score(q, c):
    if not q or not c or c == "unknown": return 0.3
    return 1.0 if q == c else 0.7 if (q in NEUTRAL and c in NEUTRAL) else 0.1

def visual_search(img, k=5, force_super=None, min_score=0.4, strict_color=True, strict_sleeve=True, strict_mid=True):
    emb, meta = store(); m, pre, _, _ = models()
    with torch.no_grad():
        q = m.encode_image(pre(img).unsqueeze(0)).numpy().flatten().astype("float32")
    q /= np.linalg.norm(q)
    sims = emb @ q; pool = np.argsort(-sims)[:50]
    best = meta[pool[0]]; sup = force_super or best["super_category"]
    qa, qmid, qsleeve = best.get("attributes"), best.get("mid_category", "other"), best.get("sleeve")
    qcolor, _ = predict_color(img)
    out = []
    for ix in pool:
        it = meta[ix]
        if it["super_category"] != sup: continue
        if strict_mid and it.get("mid_category", "other") not in COMPATIBLE_MIDS.get(qmid, [qmid]): continue
        ic = it.get("final_color")
        if strict_color and qcolor and ic and ic != qcolor and not (qcolor in NEUTRAL and ic in NEUTRAL): continue
        if strict_sleeve and qsleeve and it.get("sleeve") and it["sleeve"] != qsleeve: continue
        if not (attr_set(qa) & attr_set(it.get("attributes"))): continue
        sc = 0.6 * float(sims[ix]) + 0.2 * overlap(qa, it.get("attributes")) + 0.2 * color_score(qcolor, ic)
        if it["category"] == best["category"]: sc += 0.05
        if sc >= min_score: out.append((int(ix), sc))
    out.sort(key=lambda x: -x[1]); kept = []
    for ix, sc in out:                                   # déduplication
        if all(float(emb[ix] @ emb[j]) <= 0.95 for j, _ in kept): kept.append((ix, sc))
    return sup, qcolor, [dict(id=ix, category=meta[ix]["category"], mid=meta[ix].get("mid_category"),
                              color=meta[ix].get("final_color"), score=round(sc, 3), img=f"/search_img/{ix}.jpg")
                         for ix, sc in kept[:k]]

def read_upload(f: UploadFile):
    try: return Image.open(io.BytesIO(f.file.read())).convert("RGB")
    except Exception: raise HTTPException(400, "Image invalide")

@router.post("/similar")
def similar(file: UploadFile = File(...), k: int = Form(5), min_score: float = Form(0.4), category: str | None = Form(None)):
    sup, color, res = visual_search(read_upload(file), k=k, min_score=min_score, force_super=category or None)
    return dict(category=sup, color=color, results=res)

@router.post("/shops")
def shops(file: UploadFile = File(...), max_results: int = Form(10)):
    serp, imgbb = os.environ.get("SERPAPI_KEY"), os.environ.get("IMGBB_KEY")
    if not serp or not imgbb: raise HTTPException(500, "SERPAPI_KEY / IMGBB_KEY manquantes (fichier .env)")
    buf = io.BytesIO(); read_upload(file).save(buf, format="JPEG")
    try:
        r = requests.post("https://api.imgbb.com/1/upload", timeout=30,
                          data={"key": imgbb, "image": base64.b64encode(buf.getvalue()).decode(), "expiration": 600}).json()
        url = r["data"]["url"]
        s = requests.get("https://serpapi.com/search.json", timeout=40,
                         params={"engine": "google_lens", "url": url, "api_key": serp}).json()
    except (requests.RequestException, KeyError) as e:
        raise HTTPException(502, f"Service externe indisponible : {e}")
    if "error" in s: raise HTTPException(502, s["error"])
    prods = []
    for mt in s.get("visual_matches", [])[:max_results]:
        p = mt.get("price"); p = p.get("value") if isinstance(p, dict) else p
        prods.append(dict(shop=mt.get("source", "N/A"), price=p, title=(mt.get("title") or "")[:80], link=mt.get("link"), thumb=mt.get("thumbnail")))
    return dict(products=prods)