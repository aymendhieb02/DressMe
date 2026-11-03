"""scoring.py : The Verdict = note d'une tenue (jusqu'à 5 pièces : 4 vêtements + 1 accessoire) + styliste LLM.

Branchement (déjà fait dans api.py) :
    scoring.configure(data_dir=DATA, cat=CAT, desc=DESC, item=it)
    app.include_router(scoring.router)
    scoring.warmup()   -> charge le LLM en arrière-plan au démarrage (lifespan)

Il utilise dressme_core.py (exporté par le notebook dans data/) : même code qu'à l'entraînement.
Variables d'environnement (toutes optionnelles, à mettre dans .env) :
    DRESSME_LLM=off            désactive le LLM (message généré par un gabarit, instantané)
    DRESSME_LLM_NAME=...       modèle HuggingFace ou dossier local
                               (défaut : Qwen2.5-3B-Instruct sur GPU, Qwen2.5-1.5B-Instruct sur CPU)
    DRESSME_LLM_LANG=English   langue du styliste

IMPORTANT : tant que le LLM n'est pas chargé, /api/score/explain répond tout de suite avec le gabarit
(source = "template") au lieu de faire attendre l'utilisateur pendant le téléchargement du modèle.
"""
import json
import os
import re
import sys
import threading
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["score"])
_S: dict = {}


# ------------------------------------------------------------------ chargement
def configure(*, data_dir, cat, desc, item):
    """data_dir = dossier data/ (scorer.pt, emb_ft.npy, config.json, dressme_core.py) | item = it(i)."""
    data_dir = Path(data_dir)
    if str(data_dir) not in sys.path:
        sys.path.insert(0, str(data_dir))
    import dressme_core as core

    cfg = json.load(open(data_dir / "config.json"))
    model = core.OutfitScorer(nn.Identity(), **cfg["scorer"])      # CLIP n'est pas rechargé : les vecteurs sont dans emb_ft.npy
    model.load_state_dict(torch.load(data_dir / "scorer.pt", map_location="cpu"))
    model.eval()
    _S.update(core=core, model=model, E=torch.tensor(np.load(data_dir / "emb_ft.npy")).float(),
              cat=cat, desc=desc, item=item, K=int(cfg.get("K", core.K)),
              acc_cats=set(cfg.get("acc_cats", core.ACC_CATS)),
              bycat={c: [i for i, x in enumerate(cat) if x == c] for c in set(cat)})
    analyze.cache_clear()


@torch.no_grad()
def score_outfits(outfits):
    """Calcule la note de chaque tenue avec le modèle OutfitScorer."""
    if not _S:
        raise RuntimeError(
            "Scoring model not initialized. "
            "Check data/scorer.pt, data/emb_ft.npy, "
            "data/config.json and data/dressme_core.py."
        )

    if not outfits:
        return np.zeros(0, dtype=float)

    model = _S["model"]
    E = _S["E"]
    K = _S["K"]

    results = np.zeros(len(outfits), dtype=float)
    groups = defaultdict(list)

    for j, outfit in enumerate(outfits):
        if not 2 <= len(outfit) <= K:
            raise ValueError(f"Invalid outfit size: {len(outfit)}")

        if len(set(outfit)) != len(outfit):
            raise ValueError(f"Duplicate items in outfit: {outfit}")

        if any(i < 0 or i >= len(E) for i in outfit):
            raise ValueError(f"Invalid item index in outfit: {outfit}")

        groups[len(outfit)].append(j)

    for length, indices in groups.items():
        for start in range(0, len(indices), 512):
            batch_indices = indices[start:start + 512]

            items = torch.tensor(
                [list(outfits[j]) for j in batch_indices],
                dtype=torch.long
            )

            mask = torch.ones_like(items, dtype=torch.bool)
            scores, _ = model(E[items], mask)

            results[batch_indices] = (
                scores.detach().cpu().numpy().reshape(-1)
            )

    return results

# ------------------------------------------------------------------ note + intrus + suggestions
def _check(items):
    if not _S:
        raise HTTPException(503, "The Verdict is not installed (missing data/ files: dressme_core.py, config.json, scorer.pt, emb_ft.npy)")
    if not 2 <= len(items) <= _S["K"]:
        raise HTTPException(400, f"Pick between 2 and {_S['K']} items")
    if len(set(items)) != len(items) or any(not 0 <= i < len(_S["cat"]) for i in items):
        raise HTTPException(400, "Invalid items")
    return list(items)


def _apply(items, pos, c):                       # pos == len(items) -> AJOUT d'un accessoire
    return items + [c] if pos == len(items) else items[:pos] + [c] + items[pos + 1:]


@lru_cache(128)
def analyze(items: tuple, top=3, min_gain=0.3):
    """-> dict(score, odd, swaps=[(pos, article, nouvelle_note)]). odd : 0 = aucun intrus, sinon position + 1."""
    core, model, E, CAT = _S["core"], _S["model"], _S["E"], _S["cat"]
    items = list(items)
    with torch.no_grad():
        t = torch.tensor([items])
        s, ol = model(E[t], torch.ones_like(t, dtype=torch.bool))
    old, odd = s.item(), int(ol.argmax(1))
    if old >= 8:
        return dict(score=old, odd=odd, swaps=[])
    rows, meta = [], []
    for pos, it in enumerate(items):             # 1) remplacer un article par un article de même catégorie
        if CAT[it] == "other":
            continue
        for c in _S["bycat"].get(CAT[it], []):
            if c not in items:
                rows.append(_apply(items, pos, c)); meta.append((pos, c))
    if len(items) < _S["K"] and not any(CAT[i] in _S["acc_cats"] for i in items):    # 2) ajouter un accessoire
        for ac in sorted(_S["acc_cats"]):
            for c in _S["bycat"].get(ac, []):
                rows.append(items + [c]); meta.append((len(items), c))
    swaps = []
    if rows:
        sc = core.score_rows(model, E, rows).tolist()
        order = [i for i in sorted(range(len(sc)), key=lambda i: -sc[i]) if sc[i] - old >= min_gain][:top]
        swaps = [(meta[i][0], meta[i][1], sc[i]) for i in order]
    return dict(score=old, odd=odd, swaps=swaps)


class Items(BaseModel):
    items: list[int]


@router.post("/score")
def api_score(b: Items):
    x = _check(b.items)
    a = analyze(tuple(x))
    return dict(score=a["score"], odd=a["odd"], max_items=_S["K"],
                swaps=[dict(pos=p, action="add" if p == len(x) else "replace", item=_S["item"](c), score=s)
                       for p, c, s in a["swaps"]])


# ------------------------------------------------------------------ styliste LLM
LANG = os.environ.get("DRESSME_LLM_LANG", "English")
SYSTEM = ("You are a concise fashion stylist. A neural model has ALREADY scored the outfit. "
          "Never invent or change the score, the odd item or the suggestions: they are facts. "
          "Explain in at most 3 short sentences why the outfit works or not, using only the item descriptions given, "
          "then say which suggestion helps most (a suggestion with action 'add' means adding an accessory). "
          "Mention a previous look ONLY by repeating the field trend_vs_previous_look and, if given, "
          "what changed in changed_since_previous_look; if trend_vs_previous_look is null say nothing about a previous look. "
          f"Write in {LANG}. No markdown.")

_llm: dict = {}
_llm_failed = False
_warm_started = False
_llm_lock, _gen_lock = threading.Lock(), threading.Lock()
MEMORY: dict = defaultdict(lambda: deque(maxlen=5))      # un historique de tenues PAR utilisateur


def _llm_enabled() -> bool:
    return os.environ.get("DRESSME_LLM", "on").lower() != "off"


def _load_llm():
    """BLOQUANT (téléchargement + chargement) : appelé UNIQUEMENT depuis le thread de warmup, jamais depuis une requête."""
    global _llm_failed
    if _llm or _llm_failed or not _llm_enabled():
        return
    with _llm_lock:
        if _llm or _llm_failed:
            return
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            default = "Qwen/Qwen2.5-3B-Instruct" if dev == "cuda" else "Qwen/Qwen2.5-1.5B-Instruct"   # CPU : modèle plus léger
            name = os.environ.get("DRESSME_LLM_NAME", default)
            print(f"[scoring] loading LLM {name} on {dev} (first run downloads it; replies use the template meanwhile)...")
            tok = AutoTokenizer.from_pretrained(name)
            m = AutoModelForCausalLM.from_pretrained(name, torch_dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
            _llm.update(tok=tok, model=m, dev=dev, name=name)
            print("[scoring] LLM ready")
        except Exception as e:                    # pas de transformers, pas de mémoire, pas de réseau...
            _llm_failed = True
            print(f"[scoring] LLM unavailable, using the template message: {e!r}")


def warmup():
    """Lance le chargement du LLM en arrière-plan (une seule fois)."""
    global _warm_started
    if _warm_started or not _llm_enabled():
        return
    _warm_started = True
    threading.Thread(target=_load_llm, daemon=True).start()


@torch.no_grad()
def _ask_llm(facts):
    if not _llm:                                  # pas (encore) chargé : on ne fait PAS attendre l'utilisateur
        warmup()
        return None
    tok, model, dev = _llm["tok"], _llm["model"], _llm["dev"]
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(facts)}]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    inputs = tok(prompt, return_tensors="pt").to(dev)
    with _gen_lock:
        out = model.generate(**inputs, max_new_tokens=120, do_sample=False)
    return tok.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def _template(f):
    """Message de secours (LLM absent, en chargement, erreur, ou chiffre inventé) : uniquement des faits du modèle."""
    t = f"This look scores {f['score']}/10."
    if f["score"] >= 8:
        t += " It works well together, no change needed."
    else:
        if f["odd_item"]:
            t += f" The {f['odd_item']} is the piece that clashes most."
        if f["suggestions"]:
            s = f["suggestions"][0]
            t += (f" Adding {s['item']}" if s["action"] == "add" else f" Swapping it for {s['by']}") + f" would lift it to {s['new_score']}/10."
    if f.get("trend_vs_previous_look"):
        t += f" This look is {f['trend_vs_previous_look']}."
    return t


def _user_key(request: Request) -> str:
    from app.database import SessionLocal
    from app.auth.dependencies import session_context
    with SessionLocal() as db:
        ctx = session_context(request, db)
        user = getattr(ctx, "user", ctx)          # <- adapte si ton contexte a une autre forme
        for k in ("id", "user_id", "email"):
            v = user.get(k) if isinstance(user, dict) else getattr(user, k, None)
            if v is not None:
                return str(v)
    return "anon"


@router.post("/score/explain")
def api_explain(b: Items, request: Request):
    x = _check(b.items)
    a = analyze(tuple(x))
    D, CAT = _S["desc"], _S["cat"]
    hist = MEMORY[_user_key(request)]
    last = hist[-1] if hist else None
    if last and last["items"] == tuple(x):         # même tenue redemandée : on compare avec celle d'avant
        prev = hist[-2] if len(hist) > 1 else None
    else:
        prev = last
    trend = changed = None
    if prev:
        trend = ("higher than the previous look" if a["score"] > prev["score"] + 0.3 else
                 "lower than the previous look" if a["score"] < prev["score"] - 0.3 else "similar to the previous look")
        gone, new = set(prev["items"]) - set(x), set(x) - set(prev["items"])
        if gone or new:
            changed = dict(removed=[D[i] for i in gone], added=[D[i] for i in new])

    def act(p, c):
        return dict(action="add", item=D[c]) if p == len(x) else dict(action="replace", replace=D[x[p]], by=D[c])

    facts = dict(outfit=[D[i] for i in x], score=round(a["score"], 1),
                 odd_item=D[x[a["odd"] - 1]] if a["odd"] > 0 else None,
                 suggestions=[dict(**act(p, c), new_score=round(s, 1)) for p, c, s in a["swaps"]],
                 trend_vs_previous_look=trend, changed_since_previous_look=changed)
    text, source = None, "llm"
    try:
        text = _ask_llm(facts)
    except Exception as e:
        print(f"[scoring] LLM generation failed: {e!r}")
    if text:                                       # garde-fou : aucun chiffre ne doit être inventé
        allowed = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(facts))) | {"10", "8", "5"}
        if [n for n in re.findall(r"\d+(?:\.\d+)?", text) if n not in allowed]:
            text = None
    if not text:
        text, source = _template(facts), "template"
    if not hist or hist[-1]["items"] != tuple(x):
        hist.append(dict(items=tuple(x), score=a["score"]))
    return dict(text=text, source=source)
@router.get("/score/status")
def api_status():
    return dict(enabled=_llm_enabled(), loaded=bool(_llm), failed=_llm_failed, model=_llm.get("name"))
