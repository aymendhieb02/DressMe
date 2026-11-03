"""completion.py : Finish the Look = le GPT (semantic IDs) devine 1 ou 2 articles manquants d'une tenue de 5 pièces max.

Sorti de api.py. Branchement (fait par apply_completion_patch.py) :
    import completion
    completion.configure(data_dir=DATA, codes=CODES, item=it)
    app.include_router(completion.router)

Données : dossier  data/completion/  (produit par la cellule d'export du notebook) :
    config.json  items.json  gpt.pt  emb.npy  COLP.npy  PMI.npy
Si ce dossier n'existe pas, l'app démarre quand même et /api/complete répond 503.
"""
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["completion"])
_E = None                                          # moteur (None tant que les données ne sont pas là)
APP2MODEL_CAT = {"accessory": "other"}             # le modèle appelle "other" ce que l'app appelle "accessory"
MODEL2APP_CAT = {"other": "accessory"}

low = lambda x: str(x).lower().strip()


def pal_names(colors):
    if not colors:
        return []
    return [low(c) for c in (colors if isinstance(colors, (list, tuple)) else [colors])]


class MiniGPT(nn.Module):                          # identique au notebook
    def __init__(self, V, d=256, heads=4, layers=4, max_len=96, drop=0.15):
        super().__init__()
        self.tok = nn.Embedding(V, d); self.pos = nn.Embedding(max_len, d)
        layer = nn.TransformerEncoderLayer(d, heads, 4 * d, drop, batch_first=True, norm_first=True)
        self.tf = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.head = nn.Linear(d, V)

    def forward(self, x):
        T = x.shape[1]
        h = self.tok(x) + self.pos(torch.arange(T, device=x.device))
        mask = nn.Transformer.generate_square_subsequent_mask(T).to(x.device)
        return self.head(self.tf(h, mask=mask, is_causal=True))


def _allowed(token_lists, L):
    """Après un préfixe d'adresse, quels tokens mènent à un VRAI article ?"""
    allowed = {}
    for t in token_lists:
        for p in range(L):
            allowed.setdefault(tuple(t[:p]), set()).add(t[p])
    return {k: sorted(v) for k, v in allowed.items()}


class Engine:
    def __init__(self, d: Path, codes, item):
        cfg = json.load(open(d / "config.json"))
        meta = json.load(open(d / "items.json"))
        self.KC, self.LV = cfg["KC"], cfg["LV"]
        self.L = self.LV + 1
        self.cat_list = cfg["cat_list"]
        self.STY, self.SEA, self.COLV, self.COLORS = cfg["STY"], cfg["SEA"], cfg["COLV"], cfg["COLORS"]
        self.LAM, self.MU, self.BEAM = cfg["LAM"], cfg["MU"], cfg["BEAM"]
        self.N_CAT, self.RULE_PEN, self.PAL_W = cfg["N_CAT"], cfg["RULE_PEN"], cfg["PAL_W"]
        self.max_items = cfg.get("max_items", 5)
        KC, L = self.KC, self.L
        self.PAD, self.BOS, self.SEP, CT0 = L * KC, L * KC + 1, L * KC + 2, L * KC + 3
        self.CT = {c: CT0 + i for i, c in enumerate(self.cat_list)}
        self.CT_IDS = [self.CT[c] for c in self.cat_list]
        self.STY0 = CT0 + len(self.cat_list)
        self.SEA0 = self.STY0 + len(self.STY) + 1
        self.COL0 = self.SEA0 + len(self.SEA) + 1
        V = self.COL0 + len(self.COLV) + 1
        if V != cfg["V"]:
            raise RuntimeError(f"vocabulary mismatch: {V} != {cfg['V']} (re-export the notebook)")
        self.gpt = MiniGPT(V, **cfg["gpt"])
        self.gpt.load_state_dict(torch.load(d / "gpt.pt", map_location="cpu")); self.gpt.eval()
        self.emb, self.COLP, self.PMI = np.load(d / "emb.npy"), np.load(d / "COLP.npy"), np.load(d / "PMI.npy")
        self.mcat = meta["cat"]
        # correspondance index du modèle <-> index de l'app (via le code article)
        app_idx = {c: i for i, c in enumerate(codes)}
        self.m2a = [app_idx.get(c) for c in meta["codes"]]
        self.a2m = {a: m for m, a in enumerate(self.m2a) if a is not None}
        self.item_tokens = [[l * KC + c for l, c in enumerate(f)] for f in meta["full_codes"]]
        active = [m for m, a in enumerate(self.m2a) if a is not None]
        self.tok2item = {tuple(self.item_tokens[m]): m for m in active}
        by_cat = {c: [m for m in active if self.mcat[m] == c] for c in self.cat_list}
        self.allowed = {c: _allowed([self.item_tokens[m] for m in v], L) for c, v in by_cat.items() if v}
        self.item = item
        print(f"[completion] ready: {len(active)}/{len(meta['codes'])} articles found in the app catalog")

    # ---- tokens
    def meta_ids(self, style="", season="", colors=()):
        cs = [self.COLV.get(c, 0) for c in pal_names(colors)][:2]; cs += [0] * (2 - len(cs))
        return (self.STY.get(low(style), 0), self.SEA.get(low(season), 0), cs[0], cs[1])

    def meta_tokens(self, m, off=False):
        m = [0, 0, 0, 0] if off else list(m)
        return [self.STY0 + m[0], self.SEA0 + m[1], self.COL0 + m[2], self.COL0 + m[3]]

    def build_seq(self, ctx, mt, target=None, tcat=None):
        s = [self.BOS] + mt
        for it in ctx:
            s += [self.CT[self.mcat[it]]] + self.item_tokens[it]
        s.append(self.SEP)
        if tcat is not None:
            s.append(self.CT[tcat])
        if target is not None:
            s += self.item_tokens[target]
        return s

    def pal_vec(self, colors):
        v = np.zeros(len(self.COLORS), dtype=np.float32)
        for p in pal_names(colors):
            for j, cn in enumerate(self.COLORS):
                if cn in p:
                    v[j] = 1
        return v

    # ---- règles de cohérence (pénalité douce)
    def rule_penalty(self, ctx):
        present = {self.mcat[i] for i in ctx}
        pen = {c: 0.0 for c in self.cat_list}
        for c in present:
            if c != "other":
                pen[c] = self.RULE_PEN
        if "dress" in present:
            pen["top"] = pen["bottom"] = self.RULE_PEN
        if present & {"top", "bottom"}:
            pen["dress"] = self.RULE_PEN
        return pen

    # ---- le modèle devine ce qui manque
    @torch.no_grad()
    def cat_ranking(self, ctx, meta):
        base = self.build_seq(ctx, self.meta_tokens(meta))
        lp = F.log_softmax(self.gpt(torch.tensor([base]))[0, -1][self.CT_IDS], -1)
        pen = self.rule_penalty(ctx)
        sc = {c: lp[k].item() - pen[c] for k, c in enumerate(self.cat_list) if c in self.allowed}
        return sorted(sc.items(), key=lambda kv: -kv[1])

    @torch.no_grad()
    def beam_items(self, base, allowed):
        """Beam search contraint : le modèle écrit l'ID token par token, uniquement vers de vrais articles."""
        beams = [(0.0, [])]
        for _ in range(self.L):
            lp = F.log_softmax(self.gpt(torch.tensor([base + b[1] for b in beams]))[:, -1], -1)
            cand = []
            for (s, pref), row in zip(beams, lp):
                ts = allowed.get(tuple(pref), [])
                if ts:
                    cand += [(s + v, pref + [t]) for t, v in zip(ts, row[ts].tolist())]
            if not cand:
                return []
            beams = sorted(cand, key=lambda c: -c[0])[:self.BEAM]
        return [(self.tok2item[tuple(p)], s) for s, p in beams if tuple(p) in self.tok2item]

    @torch.no_grad()
    def generate(self, ctx, meta, tcat=None):
        """[(article, score, catégorie)] triés. tcat donné -> catégorie imposée ; None -> le modèle décide."""
        base = self.build_seq(ctx, self.meta_tokens(meta))
        if tcat is not None:
            res = [(i, s, tcat) for i, s in self.beam_items(base + [self.CT[tcat]], self.allowed.get(tcat, {}))]
        else:
            res = []
            for c, cs in self.cat_ranking(ctx, meta)[:self.N_CAT]:
                res += [(i, cs + s, c) for i, s in self.beam_items(base + [self.CT[c]], self.allowed[c])]
        return sorted([r for r in res if r[0] not in ctx], key=lambda r: -r[1])

    @torch.no_grad()
    def complete_multi(self, ctx, meta, n_items):
        """Devine n_items articles à la suite : le 1er est ajouté au contexte, puis le 2e."""
        results, cur = [], list(ctx)
        for _ in range(n_items):
            rank = self.cat_ranking(cur, meta)
            if not rank:
                break
            best_cat, cs = rank[0]
            base = self.build_seq(cur, self.meta_tokens(meta))
            items = [it for it in self.beam_items(base + [self.CT[best_cat]], self.allowed.get(best_cat, {})) if it[0] not in cur]
            if not items:
                break
            results.append((items[0][0], cs + items[0][1], best_cat))
            cur.append(items[0][0])
        return results

    # ---- couleurs + diversité (MMR)
    def compat(self, cands, ctx, pal):
        Pc, Px = self.COLP[cands], self.COLP[ctx]
        s = (Pc @ self.PMI @ Px.T).mean(1)
        if pal is not None and pal.sum() > 0:
            s = s + self.PAL_W * (Pc @ pal) / pal.sum()
        return s

    def rerank(self, res, ctx, pal, topn):
        if not res:
            return []
        items = np.array([r[0] for r in res]); sc = np.array([r[1] for r in res], dtype=np.float64)
        sc = sc + self.LAM * self.compat(items, ctx, pal)
        E = self.emb[items]; sim = E @ E.T
        chosen = []
        while len(chosen) < min(topn, len(items)):
            div = sim[:, chosen].max(1) if chosen else np.zeros(len(items))
            val = sc - self.MU * div
            val[chosen] = -1e9
            chosen.append(int(val.argmax()))
        return [res[j] for j in chosen]

    # ---- fonction "produit"
    def run(self, ctx, style, season, colors, want, n_items, topn):
        meta, pal = self.meta_ids(style, season, colors), self.pal_vec(colors)
        cats = []
        if n_items == 1:
            if want is None:
                cats = self.cat_ranking(ctx, meta)[:3]
            res = self.rerank(self.generate(ctx, meta, want), ctx, pal, topn)
        else:
            res = self.rerank(self.complete_multi(ctx, meta, n_items), ctx, pal, n_items)
        return [r[0] for r in res], cats


def configure(*, data_dir, codes, item):
    """codes = CODES (codes article du catalogue de l'app) | item = it(i)."""
    global _E
    d = Path(data_dir) / "completion"
    if not (d / "config.json").is_file():
        print(f"[completion] {d} not found: Finish the Look disabled (export the notebook, unzip into data/)")
        return
    _E = Engine(d, codes, item)


# ------------------------------------------------------------------ routes
class CompleteIn(BaseModel):
    items: list[int]
    n_items: int = 1                 # 1 ou 2 articles à deviner
    want: str | None = None          # catégorie demandée (seulement si n_items == 1) ; None = le modèle décide
    style: str = ""
    season: str = ""
    colors: list[str] = []


@router.get("/complete/options")
def complete_options():
    if _E is None:
        return dict(styles=[], seasons=[], colors=[])
    return dict(styles=list(_E.STY), seasons=list(_E.SEA), colors=list(_E.COLV))


@router.post("/complete")
def api_complete(b: CompleteIn):
    if _E is None:
        raise HTTPException(503, "Finish the Look is not installed (missing data/completion/)")
    if b.n_items not in (1, 2):
        raise HTTPException(400, "n_items must be 1 or 2")
    if not b.items or len(set(b.items)) != len(b.items):
        raise HTTPException(400, "Add at least 1 piece (no duplicates)")
    if len(b.items) + b.n_items > _E.max_items:
        raise HTTPException(400, f"An outfit has {_E.max_items} pieces at most: with {len(b.items)} you can ask for {_E.max_items - len(b.items)} more")
    ctx = [_E.a2m[i] for i in b.items if i in _E.a2m]
    ignored = len(b.items) - len(ctx)
    if not ctx:
        raise HTTPException(422, "None of these pieces is known by the completion model")
    want = None
    if b.n_items == 1 and b.want and b.want != "auto":
        w = APP2MODEL_CAT.get(b.want, b.want)
        want = w if w in _E.allowed else None
    ids, cats = _E.run(ctx, b.style, b.season, b.colors, want, b.n_items, topn=6)
    return dict(items=[_E.item(_E.m2a[m]) for m in ids], n_items=b.n_items, ignored=ignored,
                cats=[[MODEL2APP_CAT.get(c, c), s] for c, s in cats])
