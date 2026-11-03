import base64, io, itertools, os, random, sqlite3, threading
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np, torch
import torch.nn.functional as F
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

try:                                  # api.py appelle load_dotenv() APRÈS l'import de ce fichier : on le fait ici aussi
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

router = APIRouter(prefix="/api/wardrobe", tags=["wardrobe"])

BASE = {"separates": ("top", "bottom", "shoes"), "dress": ("dress", "shoes")}   # tenues de base
BASE_CATS = {"top", "bottom", "dress", "shoes"}
LAYERS = ("outer", "bag")                  # pièces optionnelles ajoutées à la base (max 4 pièces au total)
ALL_CATS = ("top", "bottom", "dress", "shoes", "outer", "bag")
THR = 7.0                                  # valeur de repli si la calibration automatique est impossible
CAP_COUNT, CAP_CAND, CAP_LOOKS = 6000, 120, 4000   # nb max de tenues évaluées (comptage / par candidat / tenues finales)
LAYER_WEIGHT = 0.35                        # une veste/un sac "superpose" des tenues existantes : il compte moins
DECAY = 0.3                                # rendements décroissants : la 4e chemise vaut moins que la 1re paire de chaussures


def A():                       # import tardif : évite l'import circulaire avec api.py
    import api
    return api


class WIn(BaseModel):
    items: list[int]
    n: int = 3
    thr: float | None = None        # None = seuil calibré automatiquement sur de vraies tenues
    full_look: bool = True          # True = on veut aussi un sac/accessoire (tenue top+bottom+shoes+sac)
    gender: str = "women"           # "men" => la catégorie dress est ignorée


class LIn(BaseModel):
    items: list[int]
    new: list[int] = []
    k: int = 6
    need_bag: bool = True
    thr: float | None = None
    gender: str = "women"


# --------------------------------------------------------------------------- outils
def check(a, items):
    bad = [i for i in items if not 0 <= i < len(a.CAT)]
    if bad:
        raise HTTPException(400, f"Unknown item ids: {bad[:5]}")


def is_men(gender):
    return str(gender).lower() in ("men", "man", "male", "homme")


def allowed_cats(gender):
    """Catégories utilisables : pas de robe pour une garde-robe homme."""
    return tuple(c for c in ALL_CATS if not (is_men(gender) and c == "dress"))


def clean(a, items, gender):
    """Déduplique et retire les robes si la garde-robe est masculine."""
    cur = list(dict.fromkeys(items)); check(a, cur)
    if is_men(gender):
        cur = [i for i in cur if a.CAT[i] != "dress"]
    return cur


def by_cat(a, W):
    d = defaultdict(list)
    for i in W:
        d[a.CAT[i]].append(i)
    return d


def enum(a, W, must=None, cap=CAP_COUNT, seed=0):
    """Toutes les tenues possibles avec W ."""
    by = by_cat(a, W)
    mc = a.CAT[must] if must is not None else None
    if mc in BASE_CATS:
        by[mc] = [must]
    rng, outs, wts = random.Random(seed), [], []
    for shape, cats in BASE.items():
        if mc in BASE_CATS and mc not in cats:
            continue
        pools = [by.get(c, []) for c in cats]
        if not all(pools):
            continue
        opts = [()] + [(o,) for o in by.get("outer", [])] + [(b,) for b in by.get("bag", [])]
        if shape == "dress":
            opts += [(o, b) for o in by.get("outer", []) for b in by.get("bag", [])]
        if mc in LAYERS:
            opts = [x for x in opts if must in x]
        if not opts:
            continue
        bases = list(itertools.product(*pools))
        total = len(bases) * len(opts)
        if total <= cap:
            pairs, w = [(b, o) for b in bases for o in opts], 1.0
        else:
            pairs = [(bases[k // len(opts)], opts[k % len(opts)]) for k in rng.sample(range(total), cap)]
            w = total / cap
        outs += [b + o for b, o in pairs]
        wts += [w] * len(pairs)
    return outs, np.array(wts, dtype=float)


def score_outfits(a, outs):
    """Note /10 de chaque tenue avec le Scorer de ta camarade (inchangé)."""
    if not outs:
        return np.zeros(0)
    res = np.zeros(len(outs)); groups = {}
    for j, o in enumerate(outs):
        groups.setdefault(len(o), []).append(j)
    with torch.no_grad():
        for L, js in groups.items():
            for s in range(0, len(js), 512):
                ch = js[s:s + 512]
                x = torch.tensor(a.EMB_FT[[list(outs[j]) for j in ch]]).float()
                sc, _ = a.SC(x, torch.ones(len(ch), L, dtype=torch.bool))
                res[ch] = sc.numpy()
    return res


@lru_cache(1)
def auto_thr():
    """Seuil « tenue valide » = 30e centile des notes de VRAIES tenues (test). Remplace le 7.0 arbitraire."""
    a = A()
    outs = [tuple(o["items"][:4]) for o in a.TEST if len(o["items"]) >= 2][:400]
    if len(outs) < 20:
        return THR
    return float(np.clip(np.quantile(score_outfits(a, outs), 0.30), 5.0, 9.0))


def count_valid(a, W, thr):
    outs, w = enum(a, W)
    if not outs:
        return 0
    return int(round(float((w * (score_outfits(a, outs) >= thr)).sum())))


def missing_required(a, W, full_look=True):
    """Catégories indispensables absentes : top+bottom+shoes (ou robe+shoes si tu possèdes une robe), + sac."""
    have = {a.CAT[i] for i in W}
    sep = [c for c in BASE["separates"] if c not in have]
    dr = [c for c in BASE["dress"] if c not in have]
    miss = dr if ("dress" in have and len(dr) < len(sep)) else sep
    if full_look and "bag" not in have:
        miss = miss + ["bag"]
    return miss


def pool(a, cur, allowed=ALL_CATS, per=14, extra=5):
    """Candidats : les plus proches du style du dressing + quelques-uns au hasard (diversité), sans quasi-doublons."""
    E = a.EMB; m = E[cur].mean(0); m = m / (np.linalg.norm(m) + 1e-9)
    have, out, rng = set(cur), [], random.Random(len(cur))
    for c in allowed:
        idx = [i for i in a.BYCAT.get(c, []) if i not in have]
        if not idx:
            continue
        order = np.argsort(-(E[idx] @ m)); keep = [idx[j] for j in order[:per]]
        rest = [idx[j] for j in order[per:]]; keep += rng.sample(rest, min(extra, len(rest)))
        own = [i for i in cur if a.CAT[i] == c]
        if own:
            keep = [i for i in keep if float((E[own] @ E[i]).max()) < 0.92]
        out += keep
    return out


def order_items(a, items):
    rank = {c: k for k, c in enumerate(("top", "dress", "bottom", "shoes", "outer", "bag"))}
    return sorted(items, key=lambda i: rank.get(a.CAT[i], 9))


# --------------------------------------------------------------------------- analyse (style / couleurs)
STYLE_NAMES = ["casual", "formal", "sporty", "evening", "streetwear", "bohemian", "classic", "ethnic"]
STYLE_TXT = ["casual everyday", "formal business", "sporty athletic", "elegant evening party",
             "streetwear urban", "bohemian summer", "classic minimal", "ethnic traditional"]


@lru_cache(1)
def style_matrix():
    """Style zero-shot de TOUT le catalogue avec le CLIP déjà chargé par api.py (aucun modèle en plus)."""
    a = A()
    T = a.enc_text([f"a photo of a fashion item in {s} style" for s in STYLE_TXT]).numpy()
    z = 100.0 * (a.EMB @ T.T); z -= z.max(1, keepdims=True); p = np.exp(z)
    return p / p.sum(1, keepdims=True)


def profile(a, W):
    out = {}
    try:
        s = style_matrix()[W].mean(0)
        out["style"] = [dict(name=STYLE_NAMES[j], p=round(float(s[j]), 2)) for j in np.argsort(-s)[:3]]
    except Exception:
        pass
    try:
        P, _ = a.color_model(); c = P[W].mean(0)
        out["colors"] = [dict(name=a.COLORS[j], p=round(float(c[j]), 2)) for j in np.argsort(-c)[:3]]
    except Exception:
        pass
    return out


def analysis(a, W, thr, full_look=True):
    cnt = Counter(a.CAT[i] for i in W)
    return dict(counts={c: cnt.get(c, 0) for c in ALL_CATS}, missing=missing_required(a, W, full_look),
                outfits=count_valid(a, W, thr), thr=thr, **profile(a, W))


# --------------------------------------------------------------------------- tenues finales
def build_looks(a, W, new=(), k=6, need_bag=True, thr=None, reuse_pen=0.3):
    """Les k meilleures tenues complètes de la garde-robe W, variées (pénalité si on réutilise les mêmes pièces)."""
    outs, _ = enum(a, W, cap=CAP_LOOKS)
    if not outs:
        return []
    if need_bag and any(a.CAT[i] == "bag" for i in W):
        outs = [o for o in outs if any(a.CAT[i] == "bag" for i in o)] or outs
    sc = score_outfits(a, outs)
    order = [int(j) for j in np.argsort(-sc)[:max(80, k * 12)]]
    usage, taken, res, newset = Counter(), set(), [], set(new)
    for _ in range(k):
        best = None
        for j in order:
            if j in taken:
                continue
            adj = sc[j] - reuse_pen * sum(usage[i] for i in outs[j])
            if best is None or adj > best[0]:
                best = (adj, j)
        if best is None:
            break
        j = best[1]; taken.add(j); usage.update(outs[j])
        its = order_items(a, outs[j])
        res.append(dict(items=[a.it(i) for i in its], score=float(sc[j]), new=[i for i in its if i in newset]))
    return res


# --------------------------------------------------------------------------- complétion gloutonne
def run_completion(a, W, n, thr, full_look, gender="women"):
    allowed = allowed_cats(gender)
    cur, recs, added = list(W), [], []
    for step in range(n):
        remaining = n - step
        miss = missing_required(a, cur, full_look)
        forced = bool(miss) and remaining <= len(miss)          # catégorie indispensable vide → priorité
        cands = pool(a, cur, tuple(miss) if forced else allowed)
        if forced and not cands:
            cands = pool(a, cur, allowed)
        if any(a.CAT[i] == "outer" for i in added):             # 1 seule veste ajoutée par appel
            cands = [c for c in cands if a.CAT[c] != "outer"] or cands
        if not cands:
            break
        # --- on prépare TOUTES les tenues de TOUS les candidats, puis un seul passage dans le Scorer ---
        rows, owner, wts = [], [], []
        for j, c in enumerate(cands):
            o, w = enum(a, cur + [c], must=c, cap=CAP_CAND)
            rows += o; owner += [j] * len(o); wts += list(w)
        n_full = len(rows)
        for j, c in enumerate(cands):                           # paires (c, pièce possédée) : note de repli
            oth = [i for i in cur if a.CAT[i] != a.CAT[c]][:8]
            rows += [(c, i) for i in oth]; owner += [j] * len(oth); wts += [0.0] * len(oth)
        sc = score_outfits(a, rows)
        owner, wts = np.array(owner), np.array(wts)
        n_in = Counter(a.CAT[i] for i in cur)
        best = None
        for j, c in enumerate(cands):
            mf = np.where(owner[:n_full] == j)[0]
            mp = np.where(owner[n_full:] == j)[0] + n_full
            cat = a.CAT[c]
            if len(mf):
                s = sc[mf]; gain = float((wts[mf] * (s >= thr)).sum()); tie = float(s.mean())
                top = rows[int(mf[int(s.argmax())])]; bs = float(s.max())
            else:
                gain, tie, top, bs = 0.0, (float(sc[mp].mean()) if len(mp) else 0.0), (), None
            adj = gain * (LAYER_WEIGHT if cat in LAYERS else 1.0) / (1 + DECAY * n_in[cat])
            key = (adj, tie)
            if best is None or key > best[0]:
                best = (key, c, int(round(gain)), bs, top)
        _, c, gain, bs, top = best
        recs.append(dict(item=a.it(c), gain=gain, best_score=bs, look=[a.it(i) for i in order_items(a, top)],
                         forced=forced))
        cur.append(c); added.append(c)
    return recs, added


# --------------------------------------------------------------------------- photo réelle -> pièce de la garde-robe
# Le Scorer travaille sur les embeddings du catalogue (emb_ft.npy). Une photo réelle n'y figure pas :
# on détecte sa catégorie avec CLIP, puis on la relie à la pièce du catalogue la plus proche visuellement
# (c'est cette pièce qui sert au calcul des tenues ; l'interface affiche, elle, ta vraie photo).
PHOTO_CATS = {
    "top": ["a photo of a top", "a photo of a shirt or blouse", "a photo of a t-shirt", "a photo of a sweater"],
    "bottom": ["a photo of trousers", "a photo of jeans", "a photo of a skirt", "a photo of shorts"],
    "dress": ["a photo of a dress", "a photo of a long dress", "a photo of a summer dress"],
    "shoes": ["a photo of shoes", "a photo of sneakers", "a photo of boots", "a photo of sandals"],
    "outer": ["a photo of a jacket", "a photo of a coat", "a photo of a blazer", "a photo of a cardigan"],
    "bag": ["a photo of a handbag", "a photo of a bag", "a photo of a backpack"],
}


@lru_cache(1)
def cat_text_matrix():
    a = A(); names, rows = [], []
    for c, prompts in PHOTO_CATS.items():
        v = a.enc_text(prompts).numpy().mean(0)
        names.append(c); rows.append(v / (np.linalg.norm(v) + 1e-9))
    return names, np.stack(rows)


@lru_cache(1)
def image_tf():
    import open_clip, torchvision.transforms as T
    return T.Compose([
        T.Resize(224, interpolation=T.InterpolationMode.BICUBIC), T.CenterCrop(224),
        T.ToTensor(), T.Normalize(open_clip.OPENAI_DATASET_MEAN, open_clip.OPENAI_DATASET_STD)])


@torch.no_grad()
def enc_image(a, raw):
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    model, _ = a.clip()
    v = F.normalize(model.encode_image(image_tf()(img)[None]).float(), dim=-1)
    return v[0].numpy()


# --------------------------------------------------------------------------- comptes : profil (femme/homme) + garde-robe sauvegardée
# L'utilisateur connecté vient de la dépendance d'authentification EXISTANTE du projet (.env : DRESSME_USER_DEP=module:fonction).
def _load_user_dep():
    import importlib
    spec = os.environ.get("DRESSME_USER_DEP", "").strip()
    mods = ["app.auth.dependencies", "app.auth.deps", "app.auth.router", "app.auth.service", "app.auth",
            "app.api.deps", "app.dependencies", "app.deps", "app.security", "app.core.security", "app.core.deps"]
    cands = [spec] if spec else [f"{m}:{n}" for n in ("current_user", "get_current_user") for m in mods]
    for c in cands:
        mod, _, attr = c.partition(":")
        try:
            fn = getattr(importlib.import_module(mod), attr)
            print(f"[wardrobe] user dependency: {c}")
            return fn
        except Exception:
            continue
    print("[wardrobe] WARNING: user dependency not found -> set DRESSME_USER_DEP in .env")
    return None


USER_DEP = _load_user_dep()
GENDER_FIELDS = ("gender", "sex", "sexe", "genre", "gender_identity")


def _no_auth():
    raise HTTPException(503, "Account system not linked: set DRESSME_USER_DEP=module:function in .env")


def gender_hint(user):
    """Genre choisi à l'inscription, si le modèle User le contient (gender / sex / sexe / genre...)."""
    for k in GENDER_FIELDS:
        v = user.get(k) if isinstance(user, dict) else getattr(user, k, None)
        if v is None:
            continue
        v = str(getattr(v, "value", v)).strip().lower()
        if v in ("f", "female", "woman", "women", "femme", "girl", "feminine", "she"):
            return "women"
        if v in ("m", "male", "man", "men", "homme", "boy", "masculine", "he"):
            return "men"
    return None


def current_ctx(user=Depends(USER_DEP or _no_auth)):
    if isinstance(user, dict):
        v = user.get("id") or user.get("user_id") or user.get("sub") or user.get("email")
    else:
        v = getattr(user, "id", None) or getattr(user, "user_id", None) or getattr(user, "email", None)
    if v is None:
        raise HTTPException(401, "Not signed in")
    return dict(uid=str(v), gender=gender_hint(user), user=user)


# Stockage : petite base SQLite dédiée (var/wardrobe.db), créée automatiquement, indépendante d'alembic.
DB_PATH = Path(os.environ.get("DRESSME_WARDROBE_DB", Path(__file__).resolve().parent / "var" / "wardrobe.db"))
_lock = threading.Lock()


def with_db(fn):
    with _lock:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=10); c.row_factory = sqlite3.Row
        try:
            with c:
                return fn(c)
        finally:
            c.close()


with_db(lambda c: c.executescript("""
CREATE TABLE IF NOT EXISTS wardrobe_profile(user_id TEXT PRIMARY KEY, gender TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS wardrobe_items(user_id TEXT NOT NULL, item_id INTEGER NOT NULL, photo TEXT, pos INTEGER NOT NULL DEFAULT 0,
                                          PRIMARY KEY(user_id, item_id));
"""))
print(f"[wardrobe] database: {DB_PATH}")


class ProfileIn(BaseModel):
    gender: str


class ItemIn(BaseModel):
    i: int
    photo: str | None = None


class ItemsIn(BaseModel):
    items: list[ItemIn]


def norm_gender(g):
    g = str(g).lower()
    if g in ("men", "man", "male", "homme"):
        return "men"
    if g in ("women", "woman", "female", "femme"):
        return "women"
    return None


def random_wardrobe(a, gender, n_outfits=4, cap=14):
    """Garde-robe de départ aléatoire (pièces de vraies tenues). Jamais de robe pour un homme."""
    ids, pool_ = [], [o for o in a.TEST if len(o["items"]) >= 2]
    random.shuffle(pool_)
    for o in pool_:
        for i in o["items"]:
            if i in ids or a.CAT[i] == "other" or (is_men(gender) and a.CAT[i] == "dress"):
                continue
            ids.append(i)
        n_outfits -= 1
        if len(ids) >= cap or (n_outfits <= 0 and len(ids) >= 8):
            break
    return ids[:cap]


def ensure_profile(uid, gender):
    """Crée le profil du compte s'il n'existe pas, avec une garde-robe de départ aléatoire. Retourne (gender, created)."""
    a = A()

    def f(c):
        p = c.execute("SELECT gender FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone()
        if p:
            return p["gender"], False
        c.execute("INSERT INTO wardrobe_profile(user_id, gender, updated_at) VALUES(?,?,datetime('now'))", (uid, gender))
        return gender, True

    g, created = with_db(f)
    if created:
        rows = [(uid, i, None, k) for k, i in enumerate(random_wardrobe(a, g))]
        with_db(lambda c: c.executemany("INSERT OR IGNORE INTO wardrobe_items(user_id,item_id,photo,pos) VALUES(?,?,?,?)", rows))
        print(f"[wardrobe] new {g} wardrobe for user {uid}: {len(rows)} starter pieces")
    return g, created


def thumb_data_url(raw):
    """Miniature JPEG (360 px max) en data-URL : stockée avec la pièce, donc affichée à chaque connexion."""
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB"); img.thumbnail((360, 360))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


@router.get("/me")
def me(ctx: dict = Depends(current_ctx)):
    """Profil (women / men, ou None s'il faut le choisir) + garde-robe sauvegardée. Crée la garde-robe de départ si le compte est neuf."""
    uid, a = ctx["uid"], A()
    p = with_db(lambda c: c.execute("SELECT gender FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone())
    if not p and ctx["gender"]:                                  # genre connu depuis l'inscription -> pas de question posée
        ensure_profile(uid, ctx["gender"])
    p = with_db(lambda c: c.execute("SELECT gender FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone())
    rows = with_db(lambda c: c.execute("SELECT item_id, photo FROM wardrobe_items WHERE user_id=? ORDER BY pos", (uid,)).fetchall())
    gender = p["gender"] if p else None
    items = []
    for r in rows:
        i = r["item_id"]
        if not 0 <= i < len(a.CAT) or (gender == "men" and a.CAT[i] == "dress"):
            continue
        d = a.it(i)
        if r["photo"]:
            d["photo"] = r["photo"]
        items.append(d)
    return dict(gender=gender, items=items)


@router.post("/profile")
def set_profile(b: ProfileIn, ctx: dict = Depends(current_ctx)):
    """Choisit / change le type de garde-robe du compte. Premier choix = garde-robe de départ aléatoire."""
    g, uid, a = norm_gender(b.gender), ctx["uid"], A()
    if g is None:
        raise HTTPException(400, "gender must be 'women' or 'men'")
    cur, created = ensure_profile(uid, g)
    if not created and cur != g:
        def f(c):
            c.execute("UPDATE wardrobe_profile SET gender=?, updated_at=datetime('now') WHERE user_id=?", (g, uid))
            if g == "men":
                ids = [r[0] for r in c.execute("SELECT item_id FROM wardrobe_items WHERE user_id=?", (uid,)).fetchall()]
                c.executemany("DELETE FROM wardrobe_items WHERE user_id=? AND item_id=?",
                              [(uid, i) for i in ids if 0 <= i < len(a.CAT) and a.CAT[i] == "dress"])
        with_db(f)
    return dict(gender=g, created=created)


@router.post("/items")
def save_items(b: ItemsIn, ctx: dict = Depends(current_ctx)):
    """Remplace la garde-robe sauvegardée du compte par la liste envoyée (idempotent)."""
    uid, a = ctx["uid"], A()
    p = with_db(lambda c: c.execute("SELECT gender FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone())
    if not p:
        raise HTTPException(409, "Choose your wardrobe type (women / men) first")
    gender, seen, rows = p["gender"], set(), []
    for x in b.items[:300]:
        if x.i in seen or not 0 <= x.i < len(a.CAT) or (gender == "men" and a.CAT[x.i] == "dress"):
            continue
        ph = x.photo if (x.photo and x.photo.startswith("data:image/jpeg;base64,") and len(x.photo) < 400_000) else None
        seen.add(x.i); rows.append((uid, x.i, ph, len(rows)))

    def f(c):
        c.execute("DELETE FROM wardrobe_items WHERE user_id=?", (uid,))
        c.executemany("INSERT INTO wardrobe_items(user_id, item_id, photo, pos) VALUES(?,?,?,?)", rows)

    with_db(f)
    print(f"[wardrobe] saved {len(rows)} pieces for user {uid}")
    return dict(saved=len(rows))


@router.get("/debug")
def debug(ctx: dict = Depends(current_ctx)):
    """Diagnostic : à ouvrir dans le navigateur une fois connecté (http://localhost:8000/api/wardrobe/debug)."""
    user, uid = ctx["user"], ctx["uid"]
    try:
        cols = list(user.__table__.columns.keys())
    except Exception:
        cols = [k for k in dir(user) if not k.startswith("_")][:40]
    gv = {k: str(getattr(user, k, None))[:30] for k in cols if k in GENDER_FIELDS}
    p = with_db(lambda c: c.execute("SELECT gender FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone())
    n = with_db(lambda c: c.execute("SELECT COUNT(*) FROM wardrobe_items WHERE user_id=?", (uid,)).fetchone()[0])
    return dict(user_id=uid, gender_from_signup=ctx["gender"], gender_columns=gv, user_columns=cols,
                saved_profile=p["gender"] if p else None, saved_pieces=n, database=str(DB_PATH))


# --------------------------------------------------------------------------- routes
@router.get("/sample")
def sample(gender: str = "women"):
    a = A()
    return dict(items=[a.it(i) for i in random_wardrobe(a, gender)])


@router.post("/analyze")
def analyze(b: WIn):
    a = A(); cur = clean(a, b.items, b.gender)
    if not cur:
        raise HTTPException(400, "Add at least 1 piece")
    return analysis(a, cur, b.thr if b.thr is not None else auto_thr(), b.full_look)


@router.post("/complete")
def complete(b: WIn):
    a = A(); cur = clean(a, b.items, b.gender)
    if len(cur) < 3:
        raise HTTPException(400, "Add at least 3 pieces to your wardrobe")
    n = max(1, min(b.n, 5)); thr = b.thr if b.thr is not None else auto_thr()
    before = count_valid(a, cur, thr)
    recs, added = run_completion(a, cur, n, thr, b.full_look, b.gender)
    after = count_valid(a, cur + added, thr)
    looks = build_looks(a, cur + added, new=added, k=6, need_bag=b.full_look)
    return dict(recs=recs, before=before, after=after, looks=looks, thr=thr)


@router.post("/outfits")
def outfits_route(b: LIn):
    a = A(); cur = clean(a, b.items, b.gender)
    return dict(looks=build_looks(a, cur, new=b.new, k=max(1, min(b.k, 12)), need_bag=b.need_bag))


@router.post("/add_photo")
def add_photo(file: UploadFile = File(...), category: str = Form(""), exclude: str = Form(""),
              gender: str = Form("women")):
    """Photo réelle d'un vêtement -> catégorie (auto ou imposée) + pièce du catalogue la plus proche."""
    a = A()
    raw = file.file.read()
    if not raw or len(raw) > 12_000_000:
        raise HTTPException(400, "Empty or too large image (max 12 MB)")
    try:
        v = enc_image(a, raw)
    except Exception:
        raise HTTPException(400, "Unreadable image")
    names, T = cat_text_matrix()
    ok = [k for k, c in enumerate(names) if not (is_men(gender) and c == "dress")]
    z = 100.0 * (T[ok] @ v); z -= z.max(); p = np.exp(z); p /= p.sum()
    if category in names and names.index(category) in ok:
        cat = category; conf = 1.0
    else:
        if is_men(gender):                       # robe détectée sur une garde-robe homme -> refus explicite
            zf = 100.0 * (T @ v); zf -= zf.max(); pf = np.exp(zf); pf /= pf.sum()
            if names[int(pf.argmax())] == "dress":
                raise HTTPException(400, "This looks like a dress: dresses aren't available in the Men wardrobe.")
        k = int(p.argmax()); cat = names[ok[k]]; conf = float(p[k])
    ex = {int(x) for x in exclude.split(",") if x.strip().isdigit()}
    idx = [i for i in a.BYCAT.get(cat, []) if i not in ex]
    if not idx:
        raise HTTPException(404, f"No more catalog pieces available in category '{cat}'")
    sims = a.EMB[idx] @ v
    j = int(np.argmax(sims))
    return dict(item=a.it(idx[j]), category=cat, confidence=round(conf, 2), similarity=round(float(sims[j]), 3),
                photo=thumb_data_url(raw))
