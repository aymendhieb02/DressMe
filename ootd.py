"""Daily Edit : tenue du jour = météo + occasion + genre du profil utilisateur.

Branchement dans api.py (voir les 3 lignes en bas du fichier) :
    import ootd
    ootd.configure(emb=EMB, cat=CAT, desc=DESC, enc_text=enc_text, item=it)
    app.include_router(ootd.router)
"""
import itertools
import re
from functools import lru_cache

import numpy as np
import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["ootd"])

# ------------------------------------------------------------------ données du catalogue (injectées par api.py)
_S: dict = {}


def configure(*, emb, cat, desc, enc_text, item, gender_ok=None):
    """emb = EMB (CLIP, numpy) | cat = CAT | desc = DESC | enc_text = fonction texte->CLIP | item = it(i)
    gender_ok(i, gender) -> bool : optionnel, filtre catalogue par genre (sinon filtre par mots-clés sur DESC)."""
    _S.update(emb=emb, cat=cat, desc=desc, enc_text=enc_text, item=item, gender_ok=gender_ok,
              bycat={c: [i for i, x in enumerate(cat) if x == c] for c in set(cat)})
    tmat.cache_clear(); tvec.cache_clear(); _accessories.cache_clear()


@lru_cache(512)
def tmat(phrases: tuple):                       # une ligne CLIP (normalisée) par phrase
    return _S["enc_text"](list(phrases)).numpy()


@lru_cache(512)
def tvec(phrases: tuple):                       # moyenne normalisée des phrases
    v = tmat(phrases).mean(0)
    return v / (np.linalg.norm(v) + 1e-9)


zs = lambda x: (x - x.mean()) / (x.std() if x.std() > 1e-6 else 1.0)

# ------------------------------------------------------------------ genre
def normalize_gender(v) -> str:
    v = str(v or "").strip().lower()
    if v in {"f", "female", "woman", "women", "femme", "girl", "feminin", "féminin"}:
        return "women"
    if v in {"m", "male", "man", "men", "homme", "masculin"}:
        return "men"
    return "unisex"                              # inconnu / autre : tenues sans robe ni talons


def user_gender(request: Request) -> str:
    """Lit l'attribut `gender` de l'utilisateur connecté (session déjà validée par le middleware d'api.py)."""
    from app.database import SessionLocal
    from app.auth.dependencies import session_context
    with SessionLocal() as db:
        ctx = session_context(request, db)
        user = getattr(ctx, "user", ctx)         # <- adapte si ton contexte a une autre forme
        for key in ("gender", "sex", "genre"):
            raw = user.get(key) if isinstance(user, dict) else getattr(user, key, None)
            if raw:
                return normalize_gender(raw)
    return "unisex"


_FEM = re.compile(r"\b(dresses|dress(?!\s+(?:shirt|shoes?|pants|trousers))|gown|skirt|blouse|bra|bikini|swimsuit|"
                  r"heels?|heeled|pumps?|stilettos?|clutch|tote|leggings?|bodysuit|jumpsuit|earrings?|necklace)\b", re.I)


def _gender_ok(i, gender):
    f = _S["gender_ok"]
    if f:
        return f(i, gender)
    return gender == "women" or not _FEM.search(_S["desc"][i] or "")


# ------------------------------------------------------------------ accessoires (catégorie "other" du catalogue)
ACC_CLASSES = {
    "accessory": ["a photo of a scarf", "a photo of sunglasses", "a photo of a belt", "a photo of jewelry", "a photo of a necklace",
                  "a photo of gloves", "a photo of an umbrella", "a photo of a wrist watch"],
    "hat": ["a photo of a beanie", "a photo of a knit winter hat", "a photo of a baseball cap", "a photo of a hat"],
    "kids": ["a photo of a children's accessory", "a photo of a baby accessory", "a photo of a kids hair clip", "a photo of a toy"]}


@lru_cache(1)
def _accessories():
    """'other' = accessoires ; on écarte bonnets / chapeaux et accessoires enfant (comme dans le notebook)."""
    idx = _S["bycat"].get("other", [])
    if not idx:
        return []
    names = list(ACC_CLASSES)
    V = np.stack([tvec(tuple(ACC_CLASSES[n])) for n in names])
    best = (_S["emb"][idx] @ V.T).argmax(1)
    return [i for i, b in zip(idx, best) if names[b] == "accessory"]


def _slot_idx(slot, gender):
    base = _accessories() if slot == "accessory" else _S["bycat"].get(slot, [])
    return [i for i in base if _gender_ok(i, gender)]


# ------------------------------------------------------------------ météo
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
LABELS = dict(clear="clear sky", rain="rainy", snow="snowy", storm="stormy", fog="foggy")


class Ootd(BaseModel):
    lat: float | None = None
    lon: float | None = None
    city: str | None = None
    place: str = "My location"
    temp: float | None = None
    kind: str = "clear"
    wind: float = 10
    occasion: str | None = None                  # None | casual | meeting | fancy | date


def get_weather(b: Ootd) -> dict:
    if b.temp is not None:
        return dict(place="Simulated weather", temp=b.temp, feels=b.temp, wind=b.wind, kind=b.kind,
                    label=LABELS.get(b.kind, "cloudy"), tmin=b.temp, tmax=b.temp,
                    rain=100 if b.kind in ("rain", "storm") else 0, lat=None, lon=None)
    lat, lon, place = b.lat, b.lon, b.place
    if b.city:
        g = requests.get("https://geocoding-api.open-meteo.com/v1/search", headers=UA, timeout=10,
                         params=dict(name=b.city, count=1, language="en", format="json")).json()
        if not g.get("results"):
            raise HTTPException(404, f"Place not found : {b.city}")
        g = g["results"][0]
        lat, lon, place = g["latitude"], g["longitude"], f"{g['name']}, {g.get('country', '')}"
    if lat is None or lon is None:
        raise HTTPException(400, "Give a city, coordinates or a simulated temperature")
    r = requests.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=10, params=dict(
        latitude=lat, longitude=lon, timezone="auto", forecast_days=1,
        current="temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        daily="temperature_2m_max,temperature_2m_min,precipitation_probability_max")).json()
    c, d = r["current"], r["daily"]
    kind, label = wmo(int(c["weather_code"]))
    return dict(place=place, temp=c["temperature_2m"], feels=c["apparent_temperature"], wind=c["wind_speed_10m"],
                kind=kind, label=label, tmin=d["temperature_2m_min"][0], tmax=d["temperature_2m_max"][0],
                rain=(d["precipitation_probability_max"] or [0])[0] or 0, lat=lat, lon=lon)


is_rain = lambda w: w["kind"] in ("rain", "storm") or (w["rain"] or 0) >= 60
is_snow = lambda w: w["kind"] == "snow"
is_windy = lambda w: (w["wind"] or 0) >= 30
is_sunny = lambda w: w["kind"] == "clear" and w["feels"] >= 22

# ------------------------------------------------------------------ prompts météo (lus par CLIP, donc en anglais)
PROMPTS = {   # version FEMME (référence)
    "top": {"freezing": ["a thick warm wool sweater", "a heavy knit turtleneck"],
            "cold": ["a warm knit sweater", "a long sleeve warm top", "a cardigan"],
            "cool": ["a long sleeve shirt", "a light sweater"],
            "mild": ["a light blouse", "a short sleeve top", "a cotton shirt"],
            "hot": ["a light sleeveless top", "a thin short sleeve t-shirt", "a linen shirt"]},
    "bottom": {"freezing": ["thick warm wool trousers", "warm lined pants"], "cold": ["long trousers", "jeans"],
               "cool": ["jeans", "trousers"], "mild": ["light trousers", "a midi skirt"],
               "hot": ["shorts", "a short light skirt", "light linen trousers"]},
    "dress": {"freezing": ["a thick knit sweater dress", "a long sleeve wool dress"],
              "cold": ["a long sleeve knit dress", "a long sleeve midi dress"], "cool": ["a long sleeve dress"],
              "mild": ["a light midi dress"], "hot": ["a light sleeveless summer dress", "a linen dress"]},
    "shoes": {"freezing": ["warm winter boots"], "cold": ["ankle boots", "leather boots"], "cool": ["sneakers", "loafers"],
              "mild": ["sneakers", "flat shoes"], "hot": ["sandals", "open toe slides"]},
    "outer": {"freezing": ["a heavy winter coat", "a puffer jacket"], "cold": ["a warm coat", "a wool coat"],
              "cool": ["a light jacket", "a blazer"], "mild": ["a thin light jacket"], "hot": ["a thin light jacket"]},
    # accessoire : liste vide = pas d'accessoire pour cette tranche (jamais de bonnet / chapeau)
    "accessory": {"freezing": ["a thick warm scarf", "warm gloves"], "cold": ["a warm scarf", "gloves"],
                  "cool": ["a light scarf"], "mild": [], "hot": ["sunglasses"]}}
PROMPTS_MEN = {**PROMPTS,   # HOMME / UNISEXE : ni jupe, ni robe, ni blouse
    "top": {"freezing": ["a thick warm wool sweater", "a heavy knit turtleneck"],
            "cold": ["a warm knit sweater", "a long sleeve warm top", "a cardigan"],
            "cool": ["a long sleeve shirt", "a light sweater"],
            "mild": ["a polo shirt", "a short sleeve shirt", "a cotton shirt"],
            "hot": ["a thin short sleeve t-shirt", "a linen shirt", "a light polo shirt"]},
    "bottom": {"freezing": ["thick warm wool trousers", "warm lined pants"], "cold": ["long trousers", "jeans"],
               "cool": ["jeans", "chino trousers"], "mild": ["light chino trousers", "light trousers"],
               "hot": ["shorts", "light linen trousers"]},
    "dress": {}}
PROMPTS_BY_GENDER = {"women": PROMPTS, "men": PROMPTS_MEN, "unisex": PROMPTS_MEN}
GENDERS = tuple(PROMPTS_BY_GENDER)

EXTRA = {("outer", "rain"): ["a waterproof raincoat", "a trench coat"], ("shoes", "rain"): ["waterproof rain boots"],
         ("outer", "snow"): ["a thick puffer coat"], ("shoes", "snow"): ["snow boots"], ("outer", "wind"): ["a windbreaker jacket"],
         ("accessory", "rain"): ["an umbrella"], ("accessory", "snow"): ["warm gloves", "a thick scarf"],
         ("accessory", "sun"): ["sunglasses"]}

# ------------------------------------------------------------------ occasions
# Clés d'une config : dress (None = pas de robe | bonus), only_dress, shoe_rule, need_outer, prompts
OCCASIONS = {
    "casual": dict(label="Casual",
        women=dict(dress=0.0, prompts={
            "top": ["a casual t-shirt", "a relaxed sweatshirt", "a casual knit top"],
            "bottom": ["relaxed jeans", "casual chino pants"], "dress": ["a casual day dress"],
            "shoes": ["white sneakers", "casual flat shoes"], "outer": ["a casual denim jacket", "a bomber jacket"]}),
        men=dict(prompts={
            "top": ["a casual t-shirt", "a relaxed sweatshirt", "a casual polo shirt"],
            "bottom": ["relaxed jeans", "casual chino pants"],
            "shoes": ["white sneakers", "casual sneakers"], "outer": ["a casual denim jacket", "a bomber jacket"]})),
    "meeting": dict(label="Meeting / work",
        women=dict(need_outer=True, shoe_rule="heels_or_sneakers", prompts={
            "top": ["a button-up shirt", "a silk blouse", "a fine knit top"],
            "bottom": ["matching suit trousers", "a tailored suit skirt"],
            "shoes": ["elegant high heels", "heeled ankle boots", "clean white sneakers"],
            "outer": ["a tailored suit blazer", "a suit jacket"], "accessory": ["a leather belt", "a wrist watch"]}),
        men=dict(need_outer=True, shoe_rule="dress_or_sneakers", prompts={
            "top": ["a button-up shirt", "a fine knit sweater"], "bottom": ["matching suit trousers"],
            "shoes": ["leather oxford shoes", "leather derby shoes", "clean white sneakers"],
            "outer": ["a tailored suit jacket", "a suit blazer"],
            "accessory": ["a leather belt", "a wrist watch", "a silk tie"]})),
    "fancy": dict(label="Fancy / evening",
        women=dict(dress=0.0, only_dress=True, shoe_rule="heels", prompts={
            "top": ["an elegant satin blouse", "a sequin top", "a silk top"],
            "bottom": ["elegant wide leg trousers", "a satin skirt"],
            "dress": ["an elegant evening dress", "a cocktail dress"],
            "shoes": ["elegant high heels", "heeled ankle boots", "stiletto pumps"],
            "outer": ["an elegant evening coat", "a tuxedo blazer"],
            "accessory": ["elegant jewelry", "a statement necklace"]}),
        men=dict(need_outer=True, shoe_rule="dress_shoes", prompts={
            "top": ["a white formal dress shirt", "a dress shirt"],
            "bottom": ["matching suit trousers", "formal dress trousers"],
            "shoes": ["black leather oxford shoes", "polished dress shoes"],
            "outer": ["a tuxedo jacket", "a formal suit jacket"],
            "accessory": ["a bow tie", "a silk tie", "a wrist watch"]})),
    "date": dict(label="Date night",
        women=dict(dress=0.0, only_dress=True, shoe_rule="heels", prompts={
            "top": ["a stylish fitted top", "a silk blouse"], "bottom": ["a stylish skirt", "dark jeans"],
            "dress": ["a chic dress"], "shoes": ["heeled ankle boots", "heeled sandals", "stylish high heels"],
            "outer": ["a stylish leather jacket", "a chic blazer"], "accessory": ["delicate jewelry", "a necklace"]}),
        men=dict(shoe_rule="dress_or_sneakers", prompts={
            "top": ["a fitted shirt", "a fine knit sweater", "a polo shirt"], "bottom": ["dark jeans", "chino trousers"],
            "shoes": ["chelsea boots", "leather loafers", "clean minimalist sneakers"],
            "outer": ["a stylish leather jacket", "a casual blazer"],
            "accessory": ["a wrist watch", "a leather belt"]}))}


def occ_cfg(occasion, gender):
    cfg = dict(label=OCCASIONS[occasion]["label"], dress=None, only_dress=False, shoe_rule=None, need_outer=False, prompts={})
    cfg.update(OCCASIONS[occasion]["women" if gender == "women" else "men"])
    return cfg


COND_W, ACC_MIN, OCC_W, CONTRAST, SHOE_MARGIN = 1.5, 0.20, 2.0, 0.5, 0.0    # réglages (mêmes valeurs que le notebook)
HEEL_POS = ["high heel shoes", "stiletto pumps", "heeled ankle boots", "heeled sandals", "block heel boots"]
SNEAKER_POS = ["sneakers", "clean white sneakers", "minimalist leather sneakers"]
DRESS_SHOE_POS = ["leather oxford shoes", "derby shoes", "polished dress shoes", "leather loafers", "chelsea boots"]
FLAT_NEG = ["flat shoes", "flat sandals", "flat boots", "loafers"]
CLOG_NEG = ["clogs", "shearling lined clogs", "fur slippers", "mules", "slides", "flip flops"]
SHOE_RULES = {"heels": dict(allow=HEEL_POS, ban=FLAT_NEG + CLOG_NEG + ["sneakers"]),
              "heels_or_sneakers": dict(allow=HEEL_POS + SNEAKER_POS, ban=FLAT_NEG + CLOG_NEG),
              "dress_shoes": dict(allow=DRESS_SHOE_POS, ban=CLOG_NEG + ["sneakers", "sports running shoes"]),
              "dress_or_sneakers": dict(allow=DRESS_SHOE_POS + SNEAKER_POS, ban=CLOG_NEG + ["sports running shoes"])}

photo = lambda xs: tuple(f"a product photo of {x}" for x in xs)


def shoe_margin(idx, rule):
    r = SHOE_RULES[rule]
    E = _S["emb"][idx]
    return (E @ tmat(photo(r["allow"])).T).max(1) - (E @ tmat(photo(r["ban"])).T).max(1)


# ------------------------------------------------------------------ moteur
def slots_needed(w, occasion, use_dress, gender):
    s = ["dress", "shoes"] if use_dress else ["top", "bottom", "shoes"]
    if w["feels"] < 18 or is_rain(w) or is_snow(w) or is_windy(w) or (occasion and occ_cfg(occasion, gender)["need_outer"]):
        s.append("outer")
    s.append("accessory")                        # ignoré si rien ne le justifie
    return s


def prompt_groups(slot, w, occasion, gender, with_occ=True):
    groups = []
    base = PROMPTS_BY_GENDER[gender].get(slot, {}).get(band(w["feels"]), [])
    if base:
        groups.append((1.0, base))
    for cond, on in (("rain", is_rain(w)), ("snow", is_snow(w)), ("wind", is_windy(w)), ("sun", is_sunny(w))):
        if on and (slot, cond) in EXTRA:
            groups.append((COND_W, EXTRA[(slot, cond)]))
    if with_occ and occasion and occ_cfg(occasion, gender)["prompts"].get(slot):
        groups.append((OCC_W, occ_cfg(occasion, gender)["prompts"][slot]))
    return [(wt, list(photo(g))) for wt, g in groups]


def occasion_term(s, occasion, gender, idx):
    """(note brute, note contrastée) : ressemblance à cette occasion moins ressemblance moyenne aux autres."""
    mine = occ_cfg(occasion, gender)["prompts"].get(s)
    if not mine:
        return None
    E = _S["emb"][idx]
    plain = E @ tvec(photo(mine))
    others = [occ_cfg(o, gender)["prompts"].get(s) for o in OCCASIONS if o != occasion]
    others = [tvec(photo(p)) for p in others if p]
    if not others or CONTRAST == 0:
        return plain, plain
    return plain, plain - CONTRAST * (E @ np.mean(others, 0))


def score_slot(s, w, occasion, gender, topk):
    groups = prompt_groups(s, w, occasion, gender, with_occ=False)
    idx = _slot_idx(s, gender)
    has_occ = bool(occasion and occ_cfg(occasion, gender)["prompts"].get(s))
    if (not groups and not has_occ) or not idx:
        return None
    rule = occ_cfg(occasion, gender)["shoe_rule"] if occasion else None
    if s == "shoes" and rule:                    # occasion habillée : seulement les chaussures autorisées
        sm = shoe_margin(idx, rule)
        ok = [i for i, m in zip(idx, sm) if m > SHOE_MARGIN]
        idx = ok or [idx[j] for j in np.argsort(-sm)[:3]]
    E = _S["emb"][idx]
    z, raw, tot = 0, 0, 0.0
    for wt, g in groups:
        sim = E @ tvec(tuple(g))
        z, raw, tot = z + wt * zs(sim), raw + wt * sim, tot + wt
    if has_occ:
        plain, contrast = occasion_term(s, occasion, gender, idx)
        z, raw, tot = z + OCC_W * zs(contrast), raw + OCC_W * plain, tot + OCC_W
    z, raw = zs(z), raw / tot
    order = [j for j in np.argsort(-z) if s != "accessory" or raw[j] >= ACC_MIN]
    return [(idx[j], float(z[j])) for j in order[:topk]] or None


def best_combo(cand, gamma):
    names = list(cand)
    combos = list(itertools.product(*[cand[s] for s in names]))
    wscore = np.array([sum(z for _, z in c) / len(names) for c in combos])
    coh = []
    for c in combos:
        E = _S["emb"][[i for i, _ in c]]; n = len(c)
        coh.append(((E @ E.T).sum() - n) / (n * (n - 1)) if n > 1 else 0.0)
    tot = wscore + gamma * zs(np.array(coh))
    k = int(tot.argmax())
    return {s: i for s, (i, _) in zip(names, combos[k])}, float(tot[k])


def pick_outfit(w, occasion=None, gender="unisex", topk=5, gamma=0.5):
    cfg = occ_cfg(occasion, gender) if occasion else dict(dress=None, only_dress=False)
    dress_bonus, only_dress = cfg["dress"], cfg["only_dress"]
    results = []
    for use_dress in ([True, False] if only_dress else [False] + ([True] if dress_bonus is not None else [])):
        if only_dress and results:
            break                                # robe trouvée : on ne regarde pas haut + bas
        cand = {}
        for s in slots_needed(w, occasion, use_dress, gender):
            r = score_slot(s, w, occasion, gender, topk)
            if r:
                cand[s] = r
            elif use_dress and s == "dress":
                cand = {}; break                 # pas de robe dans le catalogue : formule robe impossible
        if cand:
            pick, sc = best_combo(cand, gamma)
            results.append((sc + ((dress_bonus or 0.0) if use_dress else 0.0), pick))
    if not results:
        raise RuntimeError("Not enough catalog pieces to build this outfit")
    return max(results, key=lambda r: r[0])[1]


# ------------------------------------------------------------------ route
@router.post("/ootd")
def api_ootd(b: Ootd, request: Request):
    gender = user_gender(request)
    if b.occasion and b.occasion not in OCCASIONS:
        raise HTTPException(400, f"Unknown occasion (choices: {list(OCCASIONS)})")
    try:
        w = get_weather(b)
    except requests.RequestException as e:
        raise HTTPException(502, f"Weather unavailable : {e}")
    try:
        pick = pick_outfit(w, b.occasion, gender)
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    label = occ_cfg(b.occasion, gender)["label"] if b.occasion else None
    text = f"{band(w['feels'])} {w['label']} day, feels like {w['feels']:.0f} degrees celsius" + (", windy" if is_windy(w) else "")
    item = _S["item"]
    return dict(weather=w, gender=gender, occasion=b.occasion, occasion_label=label, text=text,
                pick=[dict(slot=s, **item(i), prompts=[p for _, g in prompt_groups(s, w, b.occasion, gender) for p in g])
                      for s, i in pick.items()])
