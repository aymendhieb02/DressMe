import base64
import io
import itertools
import json
import os
import random
import sqlite3
import threading

from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import numpy as np
import torch
import torch.nn.functional as F

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# ENVIRONNEMENT
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


import wardrobe_owned

router = APIRouter(prefix="/api/wardrobe", tags=["wardrobe"])


BASE = {
    "separates": ("top", "bottom", "shoes"),
    "dress": ("dress", "shoes"),
}

BASE_CATS = {"top", "bottom", "dress", "shoes"}
LAYERS = ("outer", "bag")

ALL_CATS = ("top", "bottom", "dress", "shoes", "outer", "bag")

THR = 7.0

CAP_COUNT = 6000
CAP_CAND = 120
CAP_LOOKS = 4000

LAYER_WEIGHT = 0.35
DECAY = 0.3


def A():
    """Import tardif pour éviter les imports circulaires avec api.py."""
    import api
    return api


# ---------------------------------------------------------------------------
# MODELES PYDANTIC
# ---------------------------------------------------------------------------

class WIn(BaseModel):
    items: list[int]
    n: int = 3
    thr: float | None = None
    full_look: bool = True
    gender: str = "women"


class LIn(BaseModel):
    items: list[int]
    new: list[int] = []
    k: int = 6
    need_bag: bool = True
    thr: float | None = None
    gender: str = "women"


# ---------------------------------------------------------------------------
# GENRE ET CATALOGUE
# ---------------------------------------------------------------------------

def check(a, items):
    bad = [
        i for i in items
        if not isinstance(i, int) or not 0 <= i < len(a.CAT)
    ]

    if bad:
        raise HTTPException(400, f"Unknown item ids: {bad[:5]}")


def is_men(gender):
    return str(gender).strip().lower() in (
        "men", "man", "male", "homme", "m"
    )


def allowed_cats(gender):
    """Catégories utilisables selon le genre."""

    return tuple(
        c for c in ALL_CATS
        if not (is_men(gender) and c == "dress")
    )


def norm_gender(g):
    """Normalise le genre en women ou men."""

    g = str(g).strip().lower()

    if g in ("men", "man", "male", "homme", "m"):
        return "men"

    if g in ("women", "woman", "female", "femme", "f"):
        return "women"

    return None


# Fichier contenant les IDs autorisés pour chaque genre.
GENDER_PATH = Path(
    os.environ.get(
        "DRESSME_CATALOG_GENDER",
        Path(__file__).resolve().parent / "data" / "catalog_gender.json"
    )
)


def split_by_gender(a, Ew=None, Em=None, k=5):
    """
    Sépare le catalogue en pièces femme / homme avec CLIP.
    - Ew / Em : embeddings d'images des dossiers women / men (si fournis, méthode précise).
    - Sinon : seulement une comparaison de texte (méthode de repli, moins précise).
    Règles : robe = femme ; hauts, bas, vestes = un seul genre ; chaussures et sacs
    ambigus = disponibles pour les deux.
    """
    E = a.EMB

    def txt(prompts):
        v = a.enc_text(prompts).numpy().mean(0)
        return v / (np.linalg.norm(v) + 1e-9)

    prior = E @ txt(["a photo of women's clothing", "a photo of a woman's fashion item",
                     "a feminine garment"]) \
          - E @ txt(["a photo of men's clothing", "a photo of a man's fashion item",
                     "a masculine garment"])
    d = 0.5 * prior

    if Ew is not None and Em is not None and len(Ew) and len(Em):
        def topk(X):
            s = E @ X.T
            kk = min(k, s.shape[1])
            return np.sort(s, axis=1)[:, -kk:].mean(1)
        d = topk(Ew) - topk(Em) + 0.5 * prior

    soft = 0.3 * float(np.std(d))
    women, men = [], []
    for i in range(len(a.CAT)):
        c = str(a.CAT[i])
        if c == "dress":
            women.append(i)
        elif c in ("shoes", "bag", "other") and abs(float(d[i])) < soft:
            women.append(i)
            men.append(i)
        elif d[i] >= 0:
            women.append(i)
        else:
            men.append(i)
    return dict(women=women, men=men), d


@lru_cache(1)
def gender_ids():
    """IDs autorisés par genre. Lit catalog_gender.json ; s'il manque, repli automatique."""
    try:
        d = json.loads(GENDER_PATH.read_text(encoding="utf-8"))
        return {"women": {int(i) for i in d["women"]}, "men": {int(i) for i in d["men"]}}
    except Exception as e:
        print(f"[wardrobe] WARNING: {GENDER_PATH.name} introuvable ({e!r}).")
        print("[wardrobe] Repli temporaire (texte CLIP seulement, moins précis).")
        print("[wardrobe] Pour la version précise : python -m scripts.build_gender")
        try:
            split, _ = split_by_gender(A())
            return {"women": set(split["women"]), "men": set(split["men"])}
        except Exception as e2:
            print(f"[wardrobe] ERREUR repli genre : {e2!r}")
            return None


def ok_item(a, i, gender):
    """
    Vérifie si une pièce est autorisée pour le genre choisi.

    Conditions :
    - ID existant.
    - Pas de robe dans la garde-robe homme.
    - ID présent dans catalog_gender.json.
    """

    if not isinstance(i, int) or not 0 <= i < len(a.CAT):
        return False

    g = norm_gender(gender)

    if g is None:
        return False

    if g == "men" and a.CAT[i] == "dress":
        return False

    s = gender_ids()

    # Compatibilité temporaire si le fichier de genre est absent.
    if s is None:
        return True

    return i in s[g]


def clean(a, items, gender):
    """Déduplique et conserve uniquement les pièces autorisées."""

    cur = list(dict.fromkeys(items))
    check(a, cur)

    if norm_gender(gender) is None:
        raise HTTPException(400, "gender must be 'women' or 'men'")

    return [
        i for i in cur
        if ok_item(a, i, gender)
    ]


# ---------------------------------------------------------------------------
# ORGANISATION DU CATALOGUE
# ---------------------------------------------------------------------------

def by_cat(a, W):
    d = defaultdict(list)

    for i in W:
        d[a.CAT[i]].append(i)

    return d


def enum(a, W, must=None, cap=CAP_COUNT, seed=0):
    """Génère les combinaisons de tenues possibles."""

    by = by_cat(a, W)

    mc = a.CAT[must] if must is not None else None

    if mc in BASE_CATS:
        by[mc] = [must]

    rng = random.Random(seed)

    outs = []
    wts = []

    for shape, cats in BASE.items():

        if mc in BASE_CATS and mc not in cats:
            continue

        pools = [by.get(c, []) for c in cats]

        if not all(pools):
            continue

        opts = (
            [()]
            + [(o,) for o in by.get("outer", [])]
            + [(b,) for b in by.get("bag", [])]
        )

        if shape == "dress":
            opts += [
                (o, b)
                for o in by.get("outer", [])
                for b in by.get("bag", [])
            ]

        if mc in LAYERS:
            opts = [x for x in opts if must in x]

        if not opts:
            continue

        bases = list(itertools.product(*pools))

        total = len(bases) * len(opts)

        if total <= cap:
            pairs = [
                (b, o)
                for b in bases
                for o in opts
            ]

            w = 1.0

        else:
            pairs = [
                (bases[k // len(opts)], opts[k % len(opts)])
                for k in rng.sample(range(total), cap)
            ]

            w = total / cap

        outs += [b + o for b, o in pairs]
        wts += [w] * len(pairs)

    return outs, np.array(wts, dtype=float)


# ---------------------------------------------------------------------------
# SCORING DES TENUES
# ---------------------------------------------------------------------------

def score_outfits(a, outs):
    """Calcule les notes des tenues avec scoring.py."""

    if not outs:
        return np.zeros(0, dtype=float)

    return a.scoring.score_outfits(outs)


@lru_cache(1)
def auto_thr():
    """Calcule automatiquement le seuil de validité des tenues."""

    a = A()

    outs = [
        tuple(o["items"][:4])
        for o in a.TEST
        if len(o["items"]) >= 2
    ][:400]

    if len(outs) < 20:
        return THR

    scores = score_outfits(a, outs)

    return float(
        np.clip(np.quantile(scores, 0.30), 5.0, 9.0)
    )


def count_valid(a, W, thr):
    outs, w = enum(a, W)

    if not outs:
        return 0

    valid = score_outfits(a, outs) >= thr

    return int(round(float((w * valid).sum())))


# ---------------------------------------------------------------------------
# ANALYSE DU DRESSING
# ---------------------------------------------------------------------------

def missing_required(a, W, full_look=True):
    """
    Catégories indispensables absentes :
    top + bottom + shoes
    ou dress + shoes
    avec sac optionnel selon full_look.
    """

    have = {a.CAT[i] for i in W}

    sep = [
        c for c in BASE["separates"]
        if c not in have
    ]

    dr = [
        c for c in BASE["dress"]
        if c not in have
    ]

    miss = (
        dr
        if "dress" in have and len(dr) < len(sep)
        else sep
    )

    if full_look and "bag" not in have:
        miss = miss + ["bag"]

    return miss


def pool(
    a,
    cur,
    allowed=ALL_CATS,
    per=14,
    extra=5,
    gender="women"
):
    """
    Recherche les vêtements candidats les plus proches
    du style de la garde-robe.

    Filtrage strict selon le genre.
    """

    if not cur:
        return []

    E = a.EMB

    m = E[cur].mean(0)
    m = m / (np.linalg.norm(m) + 1e-9)

    have = set(cur)
    out = []

    rng = random.Random(len(cur))

    for c in allowed:

        idx = [
            i for i in a.BYCAT.get(c, [])
            if i not in have and ok_item(a, i, gender)
        ]

        if not idx:
            continue

        order = np.argsort(-(E[idx] @ m))

        keep = [
            idx[j] for j in order[:per]
        ]

        rest = [
            idx[j] for j in order[per:]
        ]

        keep += rng.sample(
            rest,
            min(extra, len(rest))
        )

        own = [
            i for i in cur
            if a.CAT[i] == c
        ]

        if own:
            keep = [
                i for i in keep
                if float((E[own] @ E[i]).max()) < 0.92
            ]

        out += keep

    return out


def order_items(a, items):
    rank = {
        c: k
        for k, c in enumerate(
            ("top", "dress", "bottom", "shoes", "outer", "bag")
        )
    }

    return sorted(
        items,
        key=lambda i: rank.get(a.CAT[i], 9)
    )


# ---------------------------------------------------------------------------
# ANALYSE DU STYLE ET DES COULEURS
# ---------------------------------------------------------------------------

STYLE_NAMES = [
    "casual",
    "formal",
    "sporty",
    "evening",
    "streetwear",
    "bohemian",
    "classic",
    "ethnic"
]

STYLE_TXT = [
    "casual everyday",
    "formal business",
    "sporty athletic",
    "elegant evening party",
    "streetwear urban",
    "bohemian summer",
    "classic minimal",
    "ethnic traditional"
]


@lru_cache(1)
def style_matrix():
    """Analyse zero-shot du style du catalogue avec CLIP."""

    a = A()

    T = a.enc_text([
        f"a photo of a fashion item in {s} style"
        for s in STYLE_TXT
    ]).numpy()

    z = 100.0 * (a.EMB @ T.T)

    z -= z.max(1, keepdims=True)

    p = np.exp(z)

    return p / p.sum(1, keepdims=True)


def profile(a, W):
    out = {}

    # Les matrices de style ne couvrent que le catalogue.
    if hasattr(a, "catalog_ids"):
        W = a.catalog_ids(W)
        if not W:
            return out

    try:
        s = style_matrix()[W].mean(0)

        out["style"] = [
            dict(
                name=STYLE_NAMES[j],
                p=round(float(s[j]), 2)
            )
            for j in np.argsort(-s)[:3]
        ]

    except Exception:
        pass

    try:
        P, _ = a.color_model()

        c = P[W].mean(0)

        out["colors"] = [
            dict(
                name=a.COLORS[j],
                p=round(float(c[j]), 2)
            )
            for j in np.argsort(-c)[:3]
        ]

    except Exception:
        pass

    return out


def analysis(a, W, thr, full_look=True):
    cnt = Counter(a.CAT[i] for i in W)

    return dict(
        counts={
            c: cnt.get(c, 0)
            for c in ALL_CATS
        },
        missing=missing_required(a, W, full_look),
        outfits=count_valid(a, W, thr),
        thr=thr,
        **profile(a, W)
    )


# ---------------------------------------------------------------------------
# GENERATION DES LOOKS
# ---------------------------------------------------------------------------

def build_looks(
    a,
    W,
    new=(),
    k=6,
    need_bag=True,
    thr=None,
    reuse_pen=0.3,
    prefer=()
):
    """Génère les meilleures tenues en limitant les répétitions."""

    outs, _ = enum(a, W, cap=CAP_LOOKS)

    if not outs:
        return []

    if need_bag and any(a.CAT[i] == "bag" for i in W):
        outs = [
            o for o in outs
            if any(a.CAT[i] == "bag" for i in o)
        ] or outs

    sc = score_outfits(a, outs)

    order = [
        int(j)
        for j in np.argsort(-sc)[:max(80, k * 12)]
    ]

    usage = Counter()
    taken = set()
    res = []
    newset = set(new)

    # Pièces réelles : au plus 2/3 des tenues en contiennent, le reste reste du catalogue.
    preferred = set(prefer)
    owned_quota = -(-2 * k // 3) if preferred else 0
    ranked = [int(j) for j in np.argsort(-sc)]
    with_owned = [j for j in ranked if preferred.intersection(outs[j])][:max(80, k * 12)]
    without_owned = [j for j in ranked if not preferred.intersection(outs[j])][:max(80, k * 12)]

    for step in range(k):

        best = None

        candidates = order

        if preferred:
            first, second = (with_owned, without_owned) if step < owned_quota else (without_owned, with_owned)
            candidates = [j for j in first if j not in taken] or second

        for j in candidates:

            if j in taken:
                continue

            adj = sc[j] - reuse_pen * sum(
                usage[i] for i in outs[j]
            )

            if best is None or adj > best[0]:
                best = (adj, j)

        if best is None:
            break

        j = best[1]

        taken.add(j)
        usage.update(outs[j])

        its = order_items(a, outs[j])

        res.append(
            dict(
                items=[a.it(i) for i in its],
                score=float(sc[j]),
                new=[i for i in its if i in newset]
            )
        )

    return res


# ---------------------------------------------------------------------------
# COMPLETION AUTOMATIQUE DU DRESSING
# ---------------------------------------------------------------------------

def run_completion(
    a,
    W,
    n,
    thr,
    full_look,
    gender="women"
):
    allowed = allowed_cats(gender)

    cur = list(W)
    recs = []
    added = []

    for step in range(n):

        remaining = n - step

        miss = missing_required(
            a,
            cur,
            full_look
        )

        forced = bool(miss) and remaining <= len(miss)

        # Recherche des candidats avec filtre de genre.
        cands = pool(
            a,
            cur,
            tuple(miss) if forced else allowed,
            gender=gender
        )

        if forced and not cands:
            cands = pool(
                a,
                cur,
                allowed,
                gender=gender
            )

        if any(a.CAT[i] == "outer" for i in added):
            cands = [
                c for c in cands
                if a.CAT[c] != "outer"
            ] or cands

        if not cands:
            break

        # Préparation des tenues candidates.
        rows = []
        owner = []
        wts = []

        for j, c in enumerate(cands):

            o, w = enum(
                a,
                cur + [c],
                must=c,
                cap=CAP_CAND
            )

            rows += o
            owner += [j] * len(o)
            wts += list(w)

        n_full = len(rows)

        # Paires de secours.
        for j, c in enumerate(cands):

            oth = [
                i for i in cur
                if a.CAT[i] != a.CAT[c]
            ][:8]

            rows += [
                (c, i) for i in oth
            ]

            owner += [j] * len(oth)
            wts += [0.0] * len(oth)

        sc = score_outfits(a, rows)

        owner = np.array(owner)
        wts = np.array(wts)

        n_in = Counter(
            a.CAT[i] for i in cur
        )

        best = None

        for j, c in enumerate(cands):

            mf = np.where(owner[:n_full] == j)[0]

            mp = np.where(owner[n_full:] == j)[0] + n_full

            cat = a.CAT[c]

            if len(mf):

                s = sc[mf]

                gain = float(
                    (wts[mf] * (s >= thr)).sum()
                )

                tie = float(s.mean())

                top = rows[
                    int(mf[int(s.argmax())])
                ]

                bs = float(s.max())

            else:

                gain = 0.0

                tie = (
                    float(sc[mp].mean())
                    if len(mp)
                    else 0.0
                )

                top = ()
                bs = None

            adj = (
                gain
                * (LAYER_WEIGHT if cat in LAYERS else 1.0)
                / (1 + DECAY * n_in[cat])
            )

            key = (adj, tie)

            if best is None or key > best[0]:
                best = (
                    key,
                    c,
                    int(round(gain)),
                    bs,
                    top
                )

        if best is None:
            break

        _, c, gain, bs, top = best

        recs.append(
            dict(
                item=a.it(c),
                gain=gain,
                best_score=bs,
                look=[
                    a.it(i)
                    for i in order_items(a, top)
                ],
                forced=forced
            )
        )

        cur.append(c)
        added.append(c)

    return recs, added


# ---------------------------------------------------------------------------
# PHOTO REELLE -> PIECE DU CATALOGUE
# ---------------------------------------------------------------------------

PHOTO_CATS = {
    "top": [
        "a photo of a top",
        "a photo of a shirt or blouse",
        "a photo of a t-shirt",
        "a photo of a sweater"
    ],

    "bottom": [
        "a photo of trousers",
        "a photo of jeans",
        "a photo of a skirt",
        "a photo of shorts"
    ],

    "dress": [
        "a photo of a dress",
        "a photo of a long dress",
        "a photo of a summer dress"
    ],

    "shoes": [
        "a photo of shoes",
        "a photo of sneakers",
        "a photo of boots",
        "a photo of sandals"
    ],

    "outer": [
        "a photo of a jacket",
        "a photo of a coat",
        "a photo of a blazer",
        "a photo of a cardigan"
    ],

    "bag": [
        "a photo of a handbag",
        "a photo of a bag",
        "a photo of a backpack"
    ]
}


@lru_cache(1)
def cat_text_matrix():
    a = A()

    names = []
    rows = []

    for c, prompts in PHOTO_CATS.items():

        v = a.enc_text(prompts).numpy().mean(0)

        names.append(c)

        rows.append(
            v / (np.linalg.norm(v) + 1e-9)
        )

    return names, np.stack(rows)


@lru_cache(1)
def image_tf():
    import open_clip
    import torchvision.transforms as T

    return T.Compose([
        T.Resize(
            224,
            interpolation=T.InterpolationMode.BICUBIC
        ),
        T.CenterCrop(224),
        T.ToTensor(),
        T.Normalize(
            open_clip.OPENAI_DATASET_MEAN,
            open_clip.OPENAI_DATASET_STD
        )
    ])


@torch.no_grad()
def enc_image(a, raw):
    from PIL import Image

    img = Image.open(
        io.BytesIO(raw)
    ).convert("RGB")

    model, _ = a.clip()

    v = F.normalize(
        model.encode_image(
            image_tf()(img)[None]
        ).float(),
        dim=-1
    )

    return v[0].numpy()


# ---------------------------------------------------------------------------
# AUTHENTIFICATION
# ---------------------------------------------------------------------------

def _load_user_dep():
    import importlib

    spec = os.environ.get(
        "DRESSME_USER_DEP",
        ""
    ).strip()

    mods = [
        "app.auth.dependencies",
        "app.auth.deps",
        "app.auth.router",
        "app.auth.service",
        "app.auth",
        "app.api.deps",
        "app.dependencies",
        "app.deps",
        "app.security",
        "app.core.security",
        "app.core.deps"
    ]

    cands = (
        [spec]
        if spec
        else [
            f"{m}:{n}"
            for n in ("current_user", "get_current_user")
            for m in mods
        ]
    )

    for c in cands:

        mod, _, attr = c.partition(":")

        try:

            fn = getattr(
                importlib.import_module(mod),
                attr
            )

            print(f"[wardrobe] user dependency: {c}")

            return fn

        except Exception:
            continue

    print(
        "[wardrobe] WARNING: user dependency not found "
        "-> set DRESSME_USER_DEP in .env"
    )

    return None


USER_DEP = _load_user_dep()

GENDER_FIELDS = (
    "gender",
    "sex",
    "sexe",
    "genre",
    "gender_identity"
)


def owned_overlay(request, a, gender):
    """Catalogue + vraies pièces du compte, ou None pour garder le chemin d'origine."""
    if not wardrobe_owned.enabled():
        return None
    identity = getattr(request.state, "assistant_identity", None)
    if not identity:
        return None
    return wardrobe_owned.overlay_for(
        a, UUID(identity["id"]), men=is_men(gender), encode=lambda raw: enc_image(a, raw)
    )


def _no_auth():
    raise HTTPException(
        503,
        "Account system not linked: set DRESSME_USER_DEP=module:function in .env"
    )


def gender_hint(user):
    """Récupère le genre choisi lors de l'inscription."""

    for k in GENDER_FIELDS:

        v = (
            user.get(k)
            if isinstance(user, dict)
            else getattr(user, k, None)
        )

        if v is None:
            continue

        v = str(
            getattr(v, "value", v)
        ).strip().lower()

        if v in (
            "f", "female", "woman", "women",
            "femme", "girl", "feminine", "she"
        ):
            return "women"

        if v in (
            "m", "male", "man", "men",
            "homme", "boy", "masculine", "he"
        ):
            return "men"

    return None


def current_ctx(user=Depends(USER_DEP or _no_auth)):

    if isinstance(user, dict):

        v = (
            user.get("id")
            or user.get("user_id")
            or user.get("sub")
            or user.get("email")
        )

    else:

        v = (
            getattr(user, "id", None)
            or getattr(user, "user_id", None)
            or getattr(user, "email", None)
        )

    if v is None:
        raise HTTPException(401, "Not signed in")

    return dict(
        uid=str(v),
        gender=gender_hint(user),
        user=user
    )


# ---------------------------------------------------------------------------
# BASE DE DONNEES SQLITE
# ---------------------------------------------------------------------------

DB_PATH = Path(
    os.environ.get(
        "DRESSME_WARDROBE_DB",
        Path(__file__).resolve().parent / "var" / "wardrobe.db"
    )
)

_lock = threading.Lock()


def with_db(fn):
    with _lock:

        DB_PATH.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        c = sqlite3.connect(
            DB_PATH,
            timeout=10
        )

        c.row_factory = sqlite3.Row

        try:
            with c:
                return fn(c)

        finally:
            c.close()


with_db(
    lambda c: c.executescript("""
        CREATE TABLE IF NOT EXISTS wardrobe_profile(
            user_id TEXT PRIMARY KEY,
            gender TEXT NOT NULL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS wardrobe_items(
            user_id TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            photo TEXT,
            pos INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, item_id)
        );
    """)
)


# ---------------------------------------------------------------------------
# MIGRATION : ajout de la colonne `seeded`
# ---------------------------------------------------------------------------

def _migrate(c):
    cols = {r["name"] for r in c.execute("PRAGMA table_info(wardrobe_profile)").fetchall()}
    if "seeded" not in cols:
        c.execute("ALTER TABLE wardrobe_profile ADD COLUMN seeded INTEGER NOT NULL DEFAULT 0")
        # les comptes qui ont déjà des pièces sont considérés comme initialisés
        c.execute("""UPDATE wardrobe_profile SET seeded=1
                     WHERE user_id IN (SELECT DISTINCT user_id FROM wardrobe_items)""")


with_db(_migrate)

print(f"[wardrobe] database: {DB_PATH}")


# ---------------------------------------------------------------------------
# MODELES DE STOCKAGE
# ---------------------------------------------------------------------------

class ProfileIn(BaseModel):
    gender: str


class ItemIn(BaseModel):
    i: int
    photo: str | None = None


class ItemsIn(BaseModel):
    items: list[ItemIn]


# ---------------------------------------------------------------------------
# GARDE-ROBES DE DEPART
# ---------------------------------------------------------------------------

def random_wardrobe(a, gender, n_outfits=4, cap=14):
    """
    Crée une garde-robe de départ aléatoire.

    Les vêtements doivent obligatoirement correspondre
    au genre choisi.
    """

    g = norm_gender(gender)

    if g is None:
        raise HTTPException(
            400,
            "gender must be 'women' or 'men'"
        )

    pool_ = []

    for o in a.TEST:

        its = [
            i for i in o["items"]
            if 0 <= i < len(a.CAT)
            and a.CAT[i] != "other"
        ]

        if (
            len(its) >= 2
            and all(ok_item(a, i, g) for i in its)
        ):
            pool_.append(its)

    random.shuffle(pool_)

    ids = []

    for its in pool_:

        for i in its:

            if i not in ids:
                ids.append(i)

        n_outfits -= 1

        if (
            len(ids) >= cap
            or (n_outfits <= 0 and len(ids) >= 8)
        ):
            break

    # Repli : quelques pièces par catégorie.
    if len(ids) < 8:

        categories = (
            ("top", 3),
            ("bottom", 2),
            ("shoes", 2),
            ("outer", 1),
            ("bag", 1),
            ("dress", 1)
        )

        for c, k in categories:

            if g == "men" and c == "dress":
                continue

            cand = [
                i for i in a.BYCAT.get(c, [])
                if ok_item(a, i, g) and i not in ids
            ]

            random.shuffle(cand)

            ids += cand[:k]

    return ids[:cap]


def seed_wardrobe(uid, gender):
    """
    Crée le profil ET les pièces de départ dans UNE SEULE transaction.
    Aucune requête concurrente ne peut donc voir un profil sans pièces.
    Retourne (genre, créé).
    """
    a = A()
    g = norm_gender(gender)
    if g is None:
        raise HTTPException(400, "gender must be 'women' or 'men'")

    row = with_db(lambda c: c.execute(
        "SELECT gender, seeded FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone())
    if row and row["seeded"]:
        return row["gender"], False

    ids = random_wardrobe(a, row["gender"] if row else g)

    def f(c):
        p = c.execute("SELECT gender, seeded FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone()
        if p and p["seeded"]:                      # une autre requête a déjà fait le travail
            return p["gender"], False
        gg = p["gender"] if p else g
        if p:
            c.execute("UPDATE wardrobe_profile SET seeded=1 WHERE user_id=?", (uid,))
        else:
            c.execute("INSERT INTO wardrobe_profile(user_id, gender, updated_at, seeded) "
                      "VALUES(?,?,datetime('now'),1)", (uid, gg))
        c.execute("DELETE FROM wardrobe_items WHERE user_id=?", (uid,))
        c.executemany("INSERT INTO wardrobe_items(user_id,item_id,photo,pos) VALUES(?,?,?,?)",
                      [(uid, i, None, k) for k, i in enumerate(ids)])
        return gg, True

    gg, created = with_db(f)
    if created:
        print(f"[wardrobe] new {gg} wardrobe for user {uid}: {len(ids)} starter pieces")
    return gg, created


def ensure_profile(uid, gender):          # nom conservé pour compatibilité
    return seed_wardrobe(uid, gender)


def load_items(uid, gender):
    """Pièces sauvegardées du compte, filtrées selon le genre."""
    a = A()
    rows = with_db(lambda c: c.execute(
        "SELECT item_id, photo FROM wardrobe_items WHERE user_id=? ORDER BY pos", (uid,)).fetchall())
    items = []
    for r in rows:
        i = int(r["item_id"])
        if not ok_item(a, i, gender or "women"):
            continue
        d = a.it(i)
        if r["photo"]:
            d["photo"] = r["photo"]
        items.append(d)
    return items


# ---------------------------------------------------------------------------
# PHOTOS
# ---------------------------------------------------------------------------

def thumb_data_url(raw):
    """Convertit une photo en miniature JPEG."""

    from PIL import Image

    img = Image.open(
        io.BytesIO(raw)
    ).convert("RGB")

    img.thumbnail((360, 360))

    buf = io.BytesIO()

    img.save(
        buf,
        "JPEG",
        quality=80
    )

    return (
        "data:image/jpeg;base64,"
        + base64.b64encode(buf.getvalue()).decode()
    )


# ---------------------------------------------------------------------------
# ROUTE : PROFIL ET GARDE-ROBE
# ---------------------------------------------------------------------------

@router.get("/me")
def me(response: Response, ctx: dict = Depends(current_ctx)):
    """Profil + garde-robe sauvegardée. Jamais mise en cache."""
    response.headers["Cache-Control"] = "no-store"
    uid = ctx["uid"]

    def read():
        return with_db(lambda c: c.execute(
            "SELECT gender, seeded FROM wardrobe_profile WHERE user_id=?", (uid,)).fetchone())

    p = read()
    if p and not p["seeded"]:
        seed_wardrobe(uid, p["gender"])                 # compte resté vide : on le remplit
        p = read()
    elif not p and ctx["gender"]:
        seed_wardrobe(uid, ctx["gender"])               # genre connu depuis l'inscription
        p = read()

    gender = p["gender"] if p else None
    result = dict(gender=gender, items=load_items(uid, gender) if gender else [])
    if wardrobe_owned.enabled():
        owned = [piece.as_item() for piece in wardrobe_owned.load_owned(UUID(uid))]
        if owned:
            result["owned"] = owned
    return result


# ---------------------------------------------------------------------------
# ROUTE : CHANGEMENT WOMEN / MEN
# ---------------------------------------------------------------------------

@router.post("/profile")
def set_profile(b: ProfileIn, response: Response, ctx: dict = Depends(current_ctx)):
    """
    Choisit / change le type de garde-robe.
    Retourne directement les pièces : le front n'a plus besoin d'un second appel.
    """
    response.headers["Cache-Control"] = "no-store"
    g, uid, a = norm_gender(b.gender), ctx["uid"], A()
    if g is None:
        raise HTTPException(400, "gender must be 'women' or 'men'")

    cur, created = seed_wardrobe(uid, g)
    if not created and cur != g:                        # changement de type : nouvelle garde-robe adaptée
        ids = random_wardrobe(a, g)

        def f(c):
            c.execute("UPDATE wardrobe_profile SET gender=?, updated_at=datetime('now') WHERE user_id=?", (g, uid))
            c.execute("DELETE FROM wardrobe_items WHERE user_id=?", (uid,))
            c.executemany("INSERT INTO wardrobe_items(user_id,item_id,photo,pos) VALUES(?,?,?,?)",
                          [(uid, i, None, k) for k, i in enumerate(ids)])
        with_db(f)

    return dict(gender=g, created=created, items=load_items(uid, g))


# ---------------------------------------------------------------------------
# ROUTE : SAUVEGARDE DES VETEMENTS
# ---------------------------------------------------------------------------

@router.post("/items")
def save_items(
    b: ItemsIn,
    ctx: dict = Depends(current_ctx)
):
    """
    Remplace la garde-robe sauvegardée.

    Vérifie chaque pièce selon le genre du compte.
    """

    uid = ctx["uid"]
    a = A()

    p = with_db(
        lambda c: c.execute(
            "SELECT gender FROM wardrobe_profile WHERE user_id=?",
            (uid,)
        ).fetchone()
    )

    if not p:
        raise HTTPException(
            409,
            "Choose your wardrobe type (women / men) first"
        )

    gender = p["gender"]

    seen = set()
    rows = []

    for x in b.items[:300]:

        if x.i in seen or not ok_item(a, x.i, gender):
            continue

        ph = (
            x.photo
            if (
                x.photo
                and x.photo.startswith("data:image/jpeg;base64,")
                and len(x.photo) < 400_000
            )
            else None
        )

        seen.add(x.i)

        rows.append(
            (uid, x.i, ph, len(rows))
        )

    def f(c):

        c.execute(
            "DELETE FROM wardrobe_items WHERE user_id=?",
            (uid,)
        )

        c.executemany(
            """
            INSERT INTO wardrobe_items
            (user_id, item_id, photo, pos)
            VALUES(?,?,?,?)
            """,
            rows
        )

    with_db(f)

    print(
        f"[wardrobe] saved {len(rows)} pieces for user {uid}"
    )

    return dict(saved=len(rows))


# ---------------------------------------------------------------------------
# ROUTE : DEBUG
# ---------------------------------------------------------------------------

@router.get("/debug")
def debug(ctx: dict = Depends(current_ctx)):

    user = ctx["user"]
    uid = ctx["uid"]

    try:
        cols = list(
            user.__table__.columns.keys()
        )

    except Exception:
        cols = [
            k for k in dir(user)
            if not k.startswith("_")
        ][:40]

    gv = {
        k: str(getattr(user, k, None))[:30]
        for k in cols
        if k in GENDER_FIELDS
    }

    p = with_db(
        lambda c: c.execute(
            "SELECT gender, seeded FROM wardrobe_profile WHERE user_id=?",
            (uid,)
        ).fetchone()
    )

    n = with_db(
        lambda c: c.execute(
            "SELECT COUNT(*) FROM wardrobe_items WHERE user_id=?",
            (uid,)
        ).fetchone()[0]
    )

    return dict(
        user_id=uid,
        gender_from_signup=ctx["gender"],
        gender_columns=gv,
        user_columns=cols,
        saved_profile=p["gender"] if p else None,
        seeded=bool(p["seeded"]) if p else None,
        saved_pieces=n,
        database=str(DB_PATH),
        gender_catalog_exists=GENDER_PATH.exists()
    )


# ---------------------------------------------------------------------------
# ROUTES DU CATALOGUE
# ---------------------------------------------------------------------------

@router.get("/sample")
def sample(gender: str = "women"):
    """Retourne une garde-robe de départ aléatoire."""

    g = norm_gender(gender)

    if g is None:
        raise HTTPException(
            400,
            "gender must be 'women' or 'men'"
        )

    a = A()

    return dict(
        items=[
            a.it(i)
            for i in random_wardrobe(a, g)
        ]
    )


@router.get("/allowed")
def allowed(gender: str = "women"):
    """
    Retourne les IDs du catalogue autorisés
    pour le genre sélectionné.

    Utilisé par le sélecteur de vêtements dans index.html.
    """

    g = norm_gender(gender)

    if g is None:
        raise HTTPException(
            400,
            "gender must be 'women' or 'men'"
        )

    a = A()

    ids = [
        i
        for i in range(len(a.CAT))
        if ok_item(a, i, g)
    ]

    return dict(
        gender=g,
        ids=ids
    )


# ---------------------------------------------------------------------------
# ROUTE : ANALYSE
# ---------------------------------------------------------------------------

@router.post("/analyze")
def analyze(b: WIn, request: Request):

    a = A()

    cur = clean(
        a,
        b.items,
        b.gender
    )

    overlay = owned_overlay(request, a, b.gender)

    if overlay:
        a, cur = overlay, cur + overlay.local_ids

    if not cur:
        raise HTTPException(
            400,
            "Add at least 1 piece"
        )

    thr = (
        b.thr
        if b.thr is not None
        else auto_thr()
    )

    return analysis(
        a,
        cur,
        thr,
        b.full_look
    )


# ---------------------------------------------------------------------------
# ROUTE : COMPLETION
# ---------------------------------------------------------------------------

@router.post("/complete")
def complete(b: WIn, request: Request):

    a = A()

    cur = clean(
        a,
        b.items,
        b.gender
    )

    overlay = owned_overlay(request, a, b.gender)

    if overlay:
        a, cur = overlay, cur + overlay.local_ids

    if len(cur) < 3:
        raise HTTPException(
            400,
            "Add at least 3 pieces to your wardrobe"
        )

    n = max(
        1,
        min(b.n, 5)
    )

    thr = (
        b.thr
        if b.thr is not None
        else auto_thr()
    )

    before = count_valid(
        a,
        cur,
        thr
    )

    recs, added = run_completion(
        a,
        cur,
        n,
        thr,
        b.full_look,
        b.gender
    )

    after = count_valid(
        a,
        cur + added,
        thr
    )

    looks = build_looks(
        a,
        cur + added,
        new=added,
        k=6,
        need_bag=b.full_look,
        prefer=overlay.local_ids if overlay else ()
    )

    result = dict(
        recs=recs,
        before=before,
        after=after,
        looks=looks,
        thr=thr
    )

    if overlay:
        result["owned_in_looks"] = overlay.mark_looks(looks)

    return result


# ---------------------------------------------------------------------------
# ROUTE : GENERATION DES TENUES
# ---------------------------------------------------------------------------

@router.post("/outfits")
def outfits_route(b: LIn, request: Request):

    a = A()

    cur = clean(
        a,
        b.items,
        b.gender
    )

    new = [
        i for i in b.new
        if ok_item(a, i, b.gender)
    ]

    overlay = owned_overlay(request, a, b.gender)

    if overlay:
        a, cur = overlay, cur + overlay.local_ids

    looks = build_looks(
        a,
        cur,
        new=new,
        k=max(1, min(b.k, 12)),
        need_bag=b.need_bag,
        prefer=overlay.local_ids if overlay else ()
    )

    result = dict(looks=looks)

    if overlay:
        result["owned_in_looks"] = overlay.mark_looks(looks)

    return result


# ---------------------------------------------------------------------------
# ROUTE : AJOUT D'UN VETEMENT PAR PHOTO
# ---------------------------------------------------------------------------

@router.post("/add_photo")
def add_photo(
    file: UploadFile = File(...),
    category: str = Form(""),
    exclude: str = Form(""),
    gender: str = Form("women")
):
    """
    Photo réelle d'un vêtement.

    1. Détecte sa catégorie avec CLIP.
    2. Vérifie le genre.
    3. Cherche la pièce du catalogue la plus proche.
    4. Retourne la miniature de la photo réelle.
    """

    g = norm_gender(gender)

    if g is None:
        raise HTTPException(
            400,
            "gender must be 'women' or 'men'"
        )

    a = A()

    raw = file.file.read()

    if not raw or len(raw) > 12_000_000:
        raise HTTPException(
            400,
            "Empty or too large image (max 12 MB)"
        )

    try:
        v = enc_image(a, raw)

    except Exception:
        raise HTTPException(
            400,
            "Unreadable image"
        )

    names, T = cat_text_matrix()

    # Exclure les robes pour les hommes.
    ok = [
        k for k, c in enumerate(names)
        if not (g == "men" and c == "dress")
    ]

    z = 100.0 * (T[ok] @ v)

    z -= z.max()

    p = np.exp(z)
    p /= p.sum()

    if category in names and names.index(category) in ok:

        cat = category
        conf = 1.0

    else:

        # Vérification explicite des robes pour les hommes.
        if g == "men":

            zf = 100.0 * (T @ v)

            zf -= zf.max()

            pf = np.exp(zf)
            pf /= pf.sum()

            if names[int(pf.argmax())] == "dress":

                raise HTTPException(
                    400,
                    "This looks like a dress: "
                    "dresses aren't available in the Men wardrobe."
                )

        k = int(p.argmax())

        cat = names[ok[k]]
        conf = float(p[k])

    # Pièces déjà présentes à exclure.
    ex = {
        int(x)
        for x in exclude.split(",")
        if x.strip().isdigit()
    }

    # Filtrage par genre ET par catégorie.
    idx = [
        i for i in a.BYCAT.get(cat, [])
        if i not in ex and ok_item(a, i, g)
    ]

    if not idx:
        raise HTTPException(
            404,
            f"No more catalog pieces available in category '{cat}'"
        )

    # Recherche de la pièce visuellement la plus proche.
    sims = a.EMB[idx] @ v

    j = int(np.argmax(sims))

    return dict(
        item=a.it(idx[j]),
        category=cat,
        confidence=round(conf, 2),
        similarity=round(float(sims[j]), 3),
        photo=thumb_data_url(raw)
    )