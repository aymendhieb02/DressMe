"""Dress Me : API.   Lancer :  uvicorn api:app --port 8000   puis ouvrir http://localhost:8000

Les 3 idées vivent chacune dans leur module :
    ootd.py        Daily Edit      (météo + occasion + genre, tenue de 4-5 pièces)
    scoring.py     The Verdict     (note d'une tenue de 2 à 5 pièces + styliste LLM)
    completion.py  Finish the Look (le GPT devine 1 ou 2 pièces, tenue de 5 pièces max)
"""
import json, os
import re
import time
from email import policy
from email.parser import BytesParser
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

# Load local configuration before importing Studio settings, database engines or services.
load_dotenv()

import numpy as np, torch
import torch.nn.functional as F
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from similar import router as similar_router
from wardrobe import router as wardrobe_router
import ootd, scoring, completion
from app.main import app as studio_app
from app.database import SessionLocal
from app.auth.dependencies import session_context, require_csrf, InvalidCsrfToken
from app.config import settings as studio_settings
from dressme.routes import router as assistant_router, bo1_router
from reco import router as reco_router
from style import router as style_router
from bubble import router as bubble_router

ROOT_DIR = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DRESSME_DATA", ROOT_DIR / "data"))
cat_json = json.load(open(DATA / "catalog.json")); OUTS = json.load(open(DATA / "outfits.json"))
CODES, DESC, CAT = cat_json["codes"], cat_json["desc"], cat_json["cat"]
EMB = np.load(DATA / "emb_clip.npy")
for o in OUTS: o.setdefault("test", o.get("split") == "test")   # nouveau format : "split" au lieu de "test"
TEST = [o for o in OUTS if o["test"]] or OUTS
MAX_ITEMS = 5

# ============================================================
# WARDROBE — Shared category index
# ============================================================

import numpy as np

CAT = np.asarray(CAT)

BYCAT = {
    category: np.flatnonzero(CAT == category).tolist()
    for category in np.unique(CAT)
}

print(
    f"[wardrobe] BYCAT ready: "
    f"{len(BYCAT)} categories, "
    f"{sum(len(v) for v in BYCAT.values())} articles"
)
# ---------------------------------------------------------------- CLIP (public, sans token) : utilisé par ootd.py
@lru_cache(1)
def clip():
    import open_clip
    m, _, _ = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
    return m.eval(), open_clip.get_tokenizer("ViT-B-32")
@torch.no_grad()
def enc_text(t):
    m, tok = clip(); return F.normalize(m.encode_text(tok(t)).float(), dim=-1)


# ---------------------------------------------------------------- API
@asynccontextmanager
async def lifespan(_app):
    scoring.warmup()          # charge le LLM du styliste en arrière-plan (la 1re réponse ne sera pas lente)
    # Mounting a FastAPI app does not enter its lifespan automatically.
    async with studio_app.router.lifespan_context(studio_app):
        yield


from redundancy import router as redundancy_router   # BO3
from donate import router as donate_router            # BO3

app = FastAPI(title="Dress Me", lifespan=lifespan)
app.state.assistant_auth_required = True

@app.middleware("http")
async def integrated_auth_boundary(request: Request, call_next):
    path = request.url.path
    protected = path.startswith(("/api/", "/img/", "/search_img/", "/reco_img/"))
    if not protected or path in {"/api/studio-config", "/api/public-style-wall", "/api/dev-recovery-message"}:
        return await call_next(request)
    with SessionLocal() as db:
        context = session_context(request, db)
        if context is not None:
            request.state.assistant_identity = dict(id=str(context.user.id), gender=context.user.gender)
            if path.startswith(('/api/assistant/', '/api/reco/', '/api/style/', '/api/bubble/')) and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                try:
                    require_csrf(request, context)
                except InvalidCsrfToken:
                    return JSONResponse({'error': {'code': 'csrf_failed', 'message': 'The request origin or CSRF token is invalid.'}}, status_code=403)
    if context is None:
        return JSONResponse({"error": {"code": "authentication_required", "message": "Sign in to use DressMe."}}, status_code=401)
    return await call_next(request)


def it(i): return dict(i=i, c=CAT[i], d=DESC[i], k=CODES[i])

# Les modules doivent être configurés AVANT de brancher leurs routes.
ootd.configure(emb=EMB, cat=CAT, desc=DESC, enc_text=enc_text, item=it)
try:
    scoring.configure(data_dir=DATA, cat=CAT, desc=DESC, item=it)
except Exception as e:      # données du Verdict absentes : l'app démarre quand même (le Verdict ne marchera pas)
    print(f"[scoring] DISABLED - copy dressme_core.py, config.json, scorer.pt, emb_ft.npy into {DATA} : {e!r}")
completion.configure(data_dir=DATA, codes=CODES, item=it)      # si data/completion/ manque : /api/complete répond 503, l'app démarre quand même

app.include_router(similar_router)
app.include_router(wardrobe_router)
app.include_router(ootd.router)         # POST /api/ootd
app.include_router(scoring.router)      # POST /api/score, /api/score/explain
app.include_router(completion.router)   # GET /api/complete/options, POST /api/complete
app.include_router(redundancy_router)   # BO3 : /api/redundancy/*
app.include_router(donate_router)       # BO3 : /api/donate/*
app.include_router(assistant_router)    # BO5 : authenticated conversation
app.include_router(bo1_router)          # BO1 : stable-ID scoring contract
app.include_router(reco_router)
app.include_router(style_router)
app.include_router(bubble_router)
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


@app.get("/api/public-style-wall")
def public_style_wall():
    """Small public sample set used only to paint the login page background."""
    return [dict(k=key) for key in CODES[:42] if (DATA / "img" / f"{key}.jpg").is_file()]


@app.get("/public-wall/{key}.jpg")
def public_wall_image(key: str):
    # These are the bundled fashion catalog samples, never user wardrobe uploads.
    if key not in CODES[:42]:
        raise HTTPException(404, "Image not found")
    image_path = DATA / "img" / f"{key}.jpg"
    if not image_path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(image_path, media_type="image/jpeg")


@app.get("/api/dev-recovery-message")
def dev_recovery_message(email: str, request: Request):
    """Read the matching local captured email; available only in loopback dev mode."""
    client_host = request.client.host if request.client else ""
    if (studio_settings.environment != "development"
            or studio_settings.email_delivery_mode != "capture"
            or client_host not in {"127.0.0.1", "::1"}):
        raise HTTPException(404, "Local mailbox is unavailable")

    address = email.strip().lower()
    now = time.time()
    cutoff = now - studio_settings.password_reset_code_ttl_seconds
    try:
        messages = sorted(studio_settings.email_capture_path.glob("*.eml"), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        messages = []
    for mail_path in messages[:100]:
        try:
            if mail_path.stat().st_mtime < cutoff or mail_path.stat().st_size > 32_768:
                continue
            message = BytesParser(policy=policy.default).parsebytes(mail_path.read_bytes())
            recipient = str(message.get("To", "")).strip().lower()
            if recipient != address:
                continue
            body_part = message.get_body(preferencelist=("plain",))
            body = body_part.get_content() if body_part else ""
            match = re.search(r"(?<!\d)\d{8}(?!\d)", body)
            if match:
                return JSONResponse(
                    {"code": match.group(0), "sent_at": int(mail_path.stat().st_mtime)},
                    headers={"Cache-Control": "no-store"},
                )
        except (OSError, ValueError, TypeError):
            continue
    raise HTTPException(404, "No recent local recovery email was found for that address")


def _public_upload_limits():
    """Only non-sensitive limits and allow-list values are exposed to the Studio UI."""
    from app.config import settings as studio_settings

    return {"upload_limits": {
        "image_bytes": studio_settings.max_upload_bytes,
        "avatar_bytes": studio_settings.max_avatar_bytes,
        "image_content_types": ["image/jpeg", "image/png", "image/webp"],
        "avatar_extensions": [".glb"],
    }, "recovery_delivery_mode": studio_settings.email_delivery_mode,
       **({"bo6_enabled": True} if studio_settings.bo6_enabled else {}),
       **({"vton_mode": "real", "vton_remote": bool(studio_settings.vton_remote_url)} if studio_settings.vton_mode == "real" else {})}


@app.get("/api/catalog")
def catalog(): return [dict(i=i, c=CAT[i], d=DESC[i], k=CODES[i]) for i in range(len(CODES))]

@app.get("/api/examples")
def examples(): return [dict(items=o["items"][:MAX_ITEMS], style=o["style"], season=o["season"]) for o in TEST[:60]]

# NB : /api/score, /api/score/explain, /api/complete, /api/complete/options et /api/ootd viennent des routeurs ci-dessus.
# L'ancien code (complete(), color_model(), cat_scores(), anciens /api/score et /api/complete) a été supprimé :
# il faisait doublon avec les modules et appelait des variables qui n'existaient plus (score, SC, EMB_FT).

app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")
app.mount("/landing", StaticFiles(directory=ROOT_DIR / "static/landing", check_dir=False), name="landing")
app.mount("/img", StaticFiles(directory=DATA / "img"), name="img")
app.mount("/search_img", StaticFiles(directory=DATA / "search_img"), name="search_img")
app.mount("/reco_img", StaticFiles(directory=DATA / "reco" / "thumbs"), name="reco_img")
@app.get("/")
def index():
    landing = ROOT_DIR / 'static/landing/index.html'
    return FileResponse(landing if landing.is_file() else ROOT_DIR / 'static/index.html')

@app.get("/login")
def login_page(): return FileResponse(ROOT_DIR / "static/index.html")

@app.get("/bo3")
def bo3_page(): return FileResponse(ROOT_DIR / "static/bo3.html", headers={"Cache-Control": "no-cache"})

@app.get("/app")
def application(): return FileResponse(ROOT_DIR / "static/index.html")
