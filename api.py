"""Dress Me : API des 3 idees des notebooks.   Lancer :  uvicorn api:app --port 8000   puis ouvrir http://localhost:8000"""
import itertools, json, os
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

# Load local configuration before importing Studio settings, database engines or services.
load_dotenv()

import numpy as np, requests, torch, torch.nn as nn, torch.nn.functional as F
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from similar import router as similar_router
from wardrobe import router as wardrobe_router     
from app.main import app as studio_app

DATA = Path(os.environ.get("DRESSME_DATA", "data"))
cat_json = json.load(open(DATA / "catalog.json")); OUTS = json.load(open(DATA / "outfits.json"))
CODES, DESC, CAT = cat_json["codes"], cat_json["desc"], cat_json["cat"]
EMB, EMB_FT = np.load(DATA / "emb_clip.npy"), np.load(DATA / "emb_ft.npy")
TEST = [o for o in OUTS if o["test"]] or OUTS
BYCAT = {c: [i for i, x in enumerate(CAT) if x == c] for c in set(CAT)}
zs = lambda x: (x - x.mean()) / (x.std() if x.std() > 1e-6 else 1.0)

# ---------------------------------------------------------------- IDEE 1 : OutfitScorer (notebook idee-scoring-vald)
class Scorer(nn.Module):   # meme architecture que OutfitScorer, sans CLIP (embeddings deja fine-tunes dans emb_ft.npy)
    def __init__(s, d=256):
        super().__init__()
        s.proj = nn.Linear(512, d); s.cls = nn.Parameter(torch.zeros(1, 1, d))
        s.tf = nn.TransformerEncoder(nn.TransformerEncoderLayer(d, 4, 4 * d, 0.1, batch_first=True), 2, enable_nested_tensor=False)
        s.score_head, s.none_head, s.odd_head = nn.Linear(d, 1), nn.Linear(d, 1), nn.Linear(d, 1)
    def forward(s, emb, mask):
        B = emb.shape[0]
        h = s.tf(torch.cat([s.cls.expand(B, -1, -1), s.proj(emb)], 1),
                 src_key_padding_mask=torch.cat([torch.zeros(B, 1, dtype=torch.bool), ~mask], 1))
        odd = s.odd_head(h[:, 1:]).squeeze(-1).masked_fill(~mask, -1e4)
        return 10 * torch.sigmoid(s.score_head(h[:, 0]).squeeze(-1)), torch.cat([s.none_head(h[:, 0]), odd], 1)
SC = Scorer(); SC.load_state_dict(torch.load(DATA / "scorer.pt", map_location="cpu")); SC.eval()

@torch.no_grad()
def score(items):
    s, odd = SC(torch.tensor(EMB_FT[items]).float()[None], torch.ones(1, len(items), dtype=torch.bool))
    return s.item(), int(odd.argmax(1))

# ---------------------------------------------------------------- CLIP (public, sans token) pour la tenue du jour
@lru_cache(1)
def clip():
    import open_clip
    m, _, _ = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
    return m.eval(), open_clip.get_tokenizer("ViT-B-32")
@torch.no_grad()
def enc_text(t):
    m, tok = clip(); return F.normalize(m.encode_text(tok(t)).float(), dim=-1)

# ---------------------------------------------------------------- IDEE 3 : tenue du jour (notebook outfit-of-the-day)
UA = {"User-Agent": "dressme/1.0"}
def wmo(c):
    if c in (0, 1): return "clear", "clear sky"
    if c in (45, 48): return "fog", "foggy"
    if 51 <= c <= 67 or 80 <= c <= 82: return "rain", "rainy"
    if 71 <= c <= 77 or c in (85, 86): return "snow", "snowy"
    if c >= 95: return "storm", "stormy"
    return "cloudy", "cloudy"
BANDS = [(-99, 5, "freezing"), (5, 12, "cold"), (12, 18, "cool"), (18, 25, "mild"), (25, 99, "hot")]
band = lambda t: next(n for lo, hi, n in BANDS if lo <= t < hi)
PROMPTS = {
 "top": {"freezing": ["a thick warm wool sweater", "a heavy knit turtleneck"], "cold": ["a warm knit sweater", "a long sleeve warm top", "a cardigan"],
         "cool": ["a long sleeve shirt", "a light sweater"], "mild": ["a light blouse", "a short sleeve top", "a cotton shirt"],
         "hot": ["a light sleeveless top", "a thin short sleeve t-shirt", "a linen shirt"]},
 "bottom": {"freezing": ["thick warm wool trousers", "warm lined pants"], "cold": ["long trousers", "jeans"], "cool": ["jeans", "trousers"],
            "mild": ["light trousers", "a midi skirt"], "hot": ["shorts", "a short light skirt", "light linen trousers"]},
 "shoes": {"freezing": ["warm winter boots"], "cold": ["ankle boots", "leather boots"], "cool": ["sneakers", "loafers"],
           "mild": ["sneakers", "flat shoes"], "hot": ["sandals", "open toe slides"]},
 "outer": {"freezing": ["a heavy winter coat", "a puffer jacket"], "cold": ["a warm coat", "a wool coat"], "cool": ["a light jacket", "a blazer"],
           "mild": ["a thin light jacket"], "hot": ["a thin light jacket"]}}
EXTRA = {("outer", "rain"): ["a waterproof raincoat", "a trench coat"], ("shoes", "rain"): ["waterproof rain boots"],
         ("outer", "snow"): ["a thick puffer coat"], ("shoes", "snow"): ["snow boots"], ("outer", "wind"): ["a windbreaker jacket"]}
is_rain = lambda w: w["kind"] in ("rain", "storm") or w["rain"] >= 60
is_snow, is_wind = (lambda w: w["kind"] == "snow"), (lambda w: w["wind"] >= 30)
def slots_needed(w): return ["top", "bottom", "shoes"] + (["outer"] if w["feels"] < 18 or is_rain(w) or is_snow(w) or is_wind(w) else [])
def groups(slot, w):
    g = [PROMPTS[slot][band(w["feels"])]]
    for cond, on in (("rain", is_rain(w)), ("snow", is_snow(w)), ("wind", is_wind(w))):
        if on and (slot, cond) in EXTRA: g.append(EXTRA[(slot, cond)])
    return [[f"a product photo of {x}" for x in gi] for gi in g]

def pick_outfit(w, topk=5, gamma=0.5):
    cand = {}
    for s in slots_needed(w):
        idx = BYCAT.get(s, [])
        if not idx: continue
        z = 0
        for k, g in enumerate(groups(s, w)):
            z = z + (1.0 if k == 0 else 1.5) * zs(EMB[idx] @ F.normalize(enc_text(g).mean(0), dim=0).numpy())
        z = zs(z); cand[s] = [(idx[j], float(z[j])) for j in np.argsort(-z)[:topk]]
    names = list(cand); combos = list(itertools.product(*[cand[s] for s in names]))
    ws = np.array([sum(z for _, z in c) / len(names) for c in combos]); coh = []
    for c in combos:
        E = EMB[[i for i, _ in c]]; n = len(c); coh.append(((E @ E.T).sum() - n) / (n * (n - 1)) if n > 1 else 0)
    best = combos[int((ws + gamma * zs(np.array(coh))).argmax())]
    return dict(zip(names, [i for i, _ in best]))

# ---------------------------------------------------------------- IDEE 2 : completion (regles + couleurs + MMR)
CATS = ["shoes", "bag", "dress", "outer", "top", "bottom", "other"]
PRESENT = [{CAT[i] for i in o["items"]} for o in OUTS if not o["test"]]
COLORS = ["black", "white", "beige", "brown", "grey", "navy", "blue", "green", "red", "pink", "yellow", "orange", "purple", "gold", "silver", "cream"]
@lru_cache(1)
def color_model():
    P = torch.softmax(torch.tensor(100 * EMB @ enc_text([f"a photo of a {c} fashion item" for c in COLORS]).numpy().T), -1).numpy()
    co = np.full((len(COLORS),) * 2, 0.5)
    for o in OUTS:
        if o["test"]: continue
        p = P[o["items"]]; s = p.sum(0); co += np.outer(s, s) - p.T @ p
    co /= co.sum(); m = co.sum(1)
    return P, np.clip(np.log(co / np.outer(m, m)), -2, 2)
def cat_scores(ctx):
    have = {CAT[i] for i in ctx}; sub = [p for p in PRESENT if have <= p] or PRESENT
    pen = {c: 3.0 if c in have and c != "other" else 0.0 for c in CATS}
    if "dress" in have: pen["top"] = pen["bottom"] = 3.0
    if have & {"top", "bottom"}: pen["dress"] = 3.0
    return {c: float(np.log((sum(c in p for p in sub) + 1) / (len(sub) + 7)) - pen[c]) for c in CATS}
def complete(ctx, want=None, topn=6, lam=1.0, mu=0.3):
    cs = cat_scores(ctx); cats = [want] if want else sorted(cs, key=cs.get, reverse=True)[:3]
    cand = [i for c in cats for i in BYCAT.get(c, []) if i not in ctx]
    P, PMI = color_model()
    sim = EMB[cand] @ F.normalize(torch.tensor(EMB[ctx]).mean(0), dim=0).numpy()
    sc = zs(sim) + lam * zs((P[cand] @ PMI @ P[ctx].T).mean(1)) + (0 if want else np.array([cs[CAT[i]] for i in cand]))
    S = EMB[cand] @ EMB[cand].T; ch = []
    while len(ch) < min(topn, len(cand)):
        v = sc - mu * (S[:, ch].max(1) if ch else 0); v[ch] = -1e9; ch.append(int(np.argmax(v)))
    return [cand[j] for j in ch], cs

# ---------------------------------------------------------------- API
@asynccontextmanager
async def lifespan(_app):
    # Mounting a FastAPI app does not enter its lifespan automatically.
    async with studio_app.router.lifespan_context(studio_app):
        yield


app = FastAPI(title="Dress Me", lifespan=lifespan)
app.include_router(similar_router)
app.include_router(wardrobe_router) 
app.mount("/studio-api", studio_app, name="studio-api")

@app.get("/api/studio-config")
def studio_config():
    """Expose only validated, public provider origins; credentials remain server-side."""
    raw = os.environ.get("AVATURN_URL", "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return {"avaturn_url": None, "export_origins": [], **_public_upload_limits()}
    allowed = (parsed.scheme == "https" and parsed.hostname is not None
               and re.fullmatch(r"[a-z0-9-]+\.avaturn\.dev", parsed.hostname, re.I)
               and parsed.netloc.lower() == parsed.hostname.lower() and parsed.path in ("", "/")
               and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
    if not allowed:
        return {"avaturn_url": None, "export_origins": [], **_public_upload_limits()}
    origins = {f"https://{parsed.hostname}"}
    for value in os.environ.get("AVATURN_EXPORT_ORIGINS", "").split(","):
        value = value.strip()
        try:
            extra = urlsplit(value)
        except ValueError:
            continue
        if (extra.scheme == "https" and extra.hostname and extra.netloc.lower() == extra.hostname.lower()
                and extra.path in ("", "/")
                and not extra.username and not extra.password and not extra.query and not extra.fragment):
            origins.add(f"https://{extra.netloc}")
    return {"avaturn_url": raw, "export_origins": sorted(origins), **_public_upload_limits()}


def _public_upload_limits():
    """Only non-sensitive limits and allow-list values are exposed to the Studio UI."""
    from app.config import settings as studio_settings

    return {"upload_limits": {
        "image_bytes": studio_settings.max_upload_bytes,
        "avatar_bytes": studio_settings.max_avatar_bytes,
        "image_content_types": ["image/jpeg", "image/png", "image/webp"],
        "avatar_extensions": [".glb"],
    }}
class Items(BaseModel): items: list[int]; want: str | None = None
class Ootd(BaseModel):
    lat: float | None = None; lon: float | None = None; city: str | None = None; place: str = "My location"
    temp: float | None = None; kind: str = "clear"; wind: float = 10
def it(i): return dict(i=i, c=CAT[i], d=DESC[i], k=CODES[i])

@app.get("/api/catalog")
def catalog(): return [dict(i=i, c=CAT[i], d=DESC[i], k=CODES[i]) for i in range(len(CODES))]
@app.get("/api/examples")
def examples(): return [dict(items=o["items"][:4], style=o["style"], season=o["season"]) for o in TEST[:60]]

@app.post("/api/score")
def api_score(b: Items):
    x = b.items
    if len(x) < 2: raise HTTPException(400, "Pick at least 2 items")
    s, odd = score(x); swaps = []
    if s < 8:
        rows, meta = [], []
        for pos, i in enumerate(x):
            if CAT[i] == "other": continue
            for c in BYCAT.get(CAT[i], []):
                if c not in x: rows.append(x[:pos] + [c] + x[pos + 1:]); meta.append((pos, c))
        if rows:
            with torch.no_grad():
                sc, _ = SC(torch.tensor(EMB_FT[rows]).float(), torch.ones(len(rows), len(x), dtype=torch.bool))
            for j in sc.argsort(descending=True).tolist():
                if sc[j] - s < 0.3 or len(swaps) == 3: break
                swaps.append(dict(pos=meta[j][0], item=it(meta[j][1]), score=sc[j].item()))
    return dict(score=s, odd=odd, swaps=swaps)

@app.post("/api/complete")
def api_complete(b: Items):
    if not b.items: raise HTTPException(400, "Add at least 1 item")
    res, cs = complete(b.items, b.want if b.want in CATS else None)
    return dict(items=[it(i) for i in res], cats=sorted(cs.items(), key=lambda kv: -kv[1])[:3])

@app.post("/api/ootd")
def api_ootd(b: Ootd):
    try:
        if b.temp is not None:
            w = dict(place="Simulated weather", temp=b.temp, feels=b.temp, wind=b.wind, kind=b.kind, label=dict(clear="clear sky", rain="rainy", snow="snowy", storm="stormy", fog="foggy").get(b.kind, "cloudy"),
                     tmin=b.temp, tmax=b.temp, rain=100 if b.kind in ("rain", "storm") else 0, lat=None, lon=None)
        else:
            lat, lon, place = b.lat, b.lon, b.place
            if b.city:
                g = requests.get("https://geocoding-api.open-meteo.com/v1/search", headers=UA, timeout=10, params=dict(name=b.city, count=1, language="en", format="json")).json()
                if not g.get("results"): raise HTTPException(404, f"Place not found : {b.city}")
                g = g["results"][0]; lat, lon, place = g["latitude"], g["longitude"], f"{g['name']}, {g.get('country', '')}"
            r = requests.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=10, params=dict(latitude=lat, longitude=lon, timezone="auto", forecast_days=1,
                current="temperature_2m,apparent_temperature,weather_code,wind_speed_10m", daily="temperature_2m_max,temperature_2m_min,precipitation_probability_max")).json()
            c, d = r["current"], r["daily"]; kind, label = wmo(int(c["weather_code"]))
            w = dict(place=place, temp=c["temperature_2m"], feels=c["apparent_temperature"], wind=c["wind_speed_10m"], kind=kind, label=label,
                     tmin=d["temperature_2m_min"][0], tmax=d["temperature_2m_max"][0], rain=(d["precipitation_probability_max"] or [0])[0] or 0, lat=lat, lon=lon)
    except requests.RequestException as e:
        raise HTTPException(502, f"Weather unavailable : {e}")
    pick = pick_outfit(w)
    text = f"{band(w['feels'])} {w['label']} day, feels like {w['feels']:.0f} degrees celsius" + (", windy" if is_wind(w) else "")
    return dict(weather=w, text=text, pick=[dict(slot=s, **it(i), prompts=[p for g in groups(s, w) for p in g]) for s, i in pick.items()])

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/img", StaticFiles(directory=DATA / "img"), name="img")
app.mount("/search_img", StaticFiles(directory=DATA / "search_img"), name="search_img")
@app.get("/")
def index(): return FileResponse("static/index.html")
