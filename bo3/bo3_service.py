"""BO3 - Detection de similarite et de redondance (module d'integration).

Une seule fonction d'entree, ``BO3.analyse_wardrobe(items)``, qui renvoie :
  * les groupes de quasi-doublons (embeddings FashionCLIP, meme categorie),
  * le score d'encombrement /100 et son niveau,
  * la carte categorie x couleur : cases sur-representees (test de Poisson),
  * les paires de la zone grise a confirmer (question fixe), les reponses de l'utilisatrice etant prises en compte,
  * optionnellement l'alerte d'achat (DOUBLON / A_CONFIRMER / SIMILAIRE / NOUVEAU) pour un article candidat.
Trois seuils : T_SIM < T_GRISE < T_DUP ; on ne compare QUE des pieces de la meme categorie.

Chaque article est un dict : {"item_id", "category", "colour", "embedding" | "image_path", "hex" (optionnel)}.
  category : articleType du catalogue (ex. "Jeans", "Tshirts") ; colour : nom de la palette de 38 teintes (ex. "Noir").
Limites : seuils valides sur un catalogue (Fashion Product Images, Small), pas sur de vraies garde-robes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import connected_components
from scipy.stats import poisson

GROUPS = {
    "Hauts": ["Tshirts", "Shirts", "Tops"],
    "Pantalons": ["Jeans", "Trousers", "Shorts"],
    "Robes / jupes": ["Dresses", "Skirts"],
    "Vestes / pulls": ["Jackets", "Sweatshirts", "Sweaters"],
    "Chaussures": ["Casual Shoes", "Heels", "Flats", "Sports Shoes", "Formal Shoes"],
    "Sacs": ["Handbags"],
    "Accessoires": [],
}
TYPE_TO_GROUP = {t: g for g, ts in GROUPS.items() for t in ts}
DATA = Path(__file__).parent / "data"
MIN_CELL_COUNT = 3
QUESTION = "Do you consider these two pieces redundant?"      # question fixe posee pour la zone grise (jamais redigee par un LLM)
GRISE_RATIO = 0.593      # position de T_GRISE entre T_SIM et T_DUP quand il n'est pas calibre : (0,851 - 0,801) / (0,885 - 0,801) avec FashionCLIP


def grise_from(t_sim: float, t_dup: float) -> float:
    """T_GRISE provisoire pour un modele sans annotations humaines : meme position relative que dans le notebook (FashionCLIP)."""
    return float(t_sim + GRISE_RATIO * (t_dup - t_sim))
SIGMA_COLOUR = 20.0
MIN_GARMENT_SHARE = 0.06      # part minimale de l'image hors fond pour que leur mediane compte comme la couleur de la piece
MAX_COLOUR_TAU = 30.0         # plafond de colour_tau : au-dela, la regle de couleur ne se declencherait presque jamais


def rgb2lab(rgb):
    """rgb : (..., 3) valeurs 0-1 ; renvoie Lab (D65). Meme formule que le notebook (pas de dependance a scikit-image)."""
    rgb = np.asarray(rgb, dtype=float)
    lin = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def colour_lab(img, tol=18):
    """Couleur d'une piece lue sur les pixels. Le fond est estime sur le cadre de l'image (mediane des bords) puis retire par remplissage depuis les bords :
    seuls les pixels proches de la couleur du fond ET relies au bord sont du fond, quel que soit son gris. Mediane en Lab des pixels restants.
    Si presque rien ne reste (vetement blanc sur fond blanc), mediane de toute l'image : le vetement blanc reste blanc."""
    from scipy.ndimage import label
    a = np.asarray(img.convert("RGB").resize((96, 96))).astype(int)
    bg = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0)
    near = np.abs(a - bg).max(axis=2) <= tol
    lab_, _ = label(near)
    edge = np.unique(np.concatenate([lab_[0], lab_[-1], lab_[:, 0], lab_[:, -1]])); edge = edge[edge > 0]
    px = a[~np.isin(lab_, edge)]
    if len(px) < MIN_GARMENT_SHARE * 96 * 96:
        px = a.reshape(-1, 3)
    return np.median(rgb2lab(px / 255.0), axis=0)


def fuse_colour(S, lab_a, lab_b, beta, sigma=SIGMA_COLOUR):
    """Similarite fusionnee : (1 - beta) * cosinus + beta * exp(-deltaE / sigma). S : cosinus (n, m) ; lab_a (n, 3) ; lab_b (m, 3)."""
    dE = np.linalg.norm(np.asarray(lab_a)[:, None, :] - np.asarray(lab_b)[None, :, :], axis=2)
    return (1 - beta) * S + beta * np.exp(-dE / sigma)


def _normalise(E: np.ndarray) -> np.ndarray:
    E = np.asarray(E, dtype=np.float32)
    return E / np.clip(np.linalg.norm(E, axis=1, keepdims=True), 1e-12, None)


def calibrate_thresholds(pos, neg):
    """Seuils a partir de cosinus de doublons fabriques (pos) et de paires quelconques (neg).
    T_DUP = milieu du plateau de F1 maximal ; T_SIM = 99e percentile de neg (meme methode que le notebook)."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    cand = np.unique(np.r_[pos, neg])
    tp = (pos[None] >= cand[:, None]).sum(1); fp = (neg[None] >= cand[:, None]).sum(1)
    f1 = 2 * tp / np.maximum(2 * tp + fp + (len(pos) - tp), 1)
    ok = np.where(f1 >= f1.max() - 1e-9)[0]
    t_dup = float((cand[ok[0]] + cand[ok[-1]]) / 2)
    t_sim = float(np.percentile(neg, 99))
    if t_sim >= t_dup:
        t_sim = t_dup - 0.05
    return t_dup, t_sim, float(f1.max())


class FashionClipEmbedder:
    """Embeddings d'images FashionCLIP (patrickjohncyh/fashion-clip). Imports paresseux : torch + transformers requis."""

    def __init__(self, model_id: str = "patrickjohncyh/fashion-clip", device: str | None = None):
        import torch
        from transformers import CLIPModel, CLIPProcessor
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = CLIPModel.from_pretrained(model_id).to(self.device).eval()
        self.proc = CLIPProcessor.from_pretrained(model_id)

    def __call__(self, paths, batch: int = 32) -> np.ndarray:
        from PIL import Image
        out = []
        for s in range(0, len(paths), batch):
            ims = [Image.open(p).convert("RGB") for p in paths[s:s + batch]]
            with self.torch.no_grad():
                f = self.model.get_image_features(**self.proc(images=ims, return_tensors="pt").to(self.device))
            out.append(f.float().cpu().numpy())
        return _normalise(np.vstack(out))


class BO3:
    def __init__(self, data_dir: str | Path = DATA, model: str = "fashionclip", embedder=None,
                 beta: float = 0.0, use_human_calibration: bool = False,
                 t_dup: float | None = None, t_sim: float | None = None, t_grise: float | None = None,
                 reference: pd.DataFrame | None = None, group_of=None, threshold_source: str | None = None,
                 colour_tau: float | None = None):
        """t_dup / t_sim / reference / group_of : a fournir pour un autre catalogue que Fashion Product Images
        (ex. l'appli DressMe : embeddings CLIP, 7 categories, reference de couleurs tiree de son propre catalogue).
        reference : DataFrame (index = groupes, colonnes = couleurs, lignes sommant a 1)."""
        d = Path(data_dir)
        self.model = model
        if t_dup is not None and t_sim is not None:
            self.t_dup, self.t_sim = float(t_dup), float(t_sim)
            self.threshold_source = threshold_source or "fournis par l'appelant"
            self.t_grise = float(t_grise) if t_grise is not None else grise_from(self.t_sim, self.t_dup)
            self.grise_source = "calibrated" if t_grise is not None else "provisional: same relative position as the FashionCLIP study (no human labels for this model)"
        else:
            th = json.loads((d / "thresholds.json").read_text())
            self.t_dup = float(th["models"][model]["T_DUP"])
            self.t_sim = float(th["models"][model]["T_SIM"])
            if use_human_calibration:                   # proposition non adoptee par defaut (un seul annotateur)
                self.t_dup = float(th["recalibrage_humain"][model]["T_DUP_F1max"])
            self.threshold_source = threshold_source or "valides sur Fashion Product Images (Small)"
            tg = th["models"][model].get("T_GRISE")
            self.t_grise = float(t_grise) if t_grise is not None else float(tg) if tg is not None else grise_from(self.t_sim, self.t_dup)
            self.grise_source = "calibrated on 155 human-labelled same-category pairs" if (t_grise is None and tg is not None) else \
                "calibrated" if t_grise is not None else "provisional: same relative position as the FashionCLIP study"
        if not (self.t_sim < self.t_grise < self.t_dup):          # garde-fou : l'ordre des trois seuils doit etre respecte
            self.t_grise = grise_from(self.t_sim, self.t_dup)
        self.group_of = group_of or TYPE_TO_GROUP.get
        lv = json.loads((d / "clutter_levels.json").read_text())
        self.sain_max, self.modere_max = lv["sain_max"], lv["modere_max"]
        ref = reference if reference is not None else pd.read_csv(d / "reference_share_fine.csv", index_col=0)
        self.ref = ref
        self.colours = list(ref.columns)
        self.alpha = 0.05 / (ref.shape[0] * ref.shape[1])
        self.beta = float(beta)                          # 0 par defaut : la couleur n'entre pas dans le score (voir README)
        self.colour_tau = float(colour_tau) if colour_tau else None   # ecart de couleur (deltaE) au-dela duquel une paire ne peut pas etre un DOUBLON automatique
        self.embedder = embedder

    # ---- bas niveau ---------------------------------------------------------------------------------
    def _embeddings(self, items):
        if all("embedding" in it for it in items):
            return _normalise(np.vstack([it["embedding"] for it in items]))
        if self.embedder is None:
            self.embedder = FashionClipEmbedder()
        miss = [i for i, it in enumerate(items) if "embedding" not in it]
        E = np.zeros((len(items), 512), dtype=np.float32)
        have = [i for i in range(len(items)) if i not in miss]
        if have:
            E[have] = _normalise(np.vstack([items[i]["embedding"] for i in have]))
        E[miss] = self.embedder([items[i]["image_path"] for i in miss])
        return E

    def _labs(self, items):
        """Couleurs Lab des pieces (cle 'lab', ou 'hex' converti) ; None si une piece n'en a pas."""
        if all("lab" in it for it in items):
            return np.array([it["lab"] for it in items], float)
        if all("hex" in it for it in items):
            rgb = np.array([[int(it["hex"][k:k + 2], 16) for k in (1, 3, 5)] for it in items], float)
            return rgb2lab(rgb / 255.0)
        return None

    def _colour_veto(self, labs):
        """Matrice booleenne : True quand deux pieces different clairement par la couleur (deltaE >= colour_tau). None si inactif."""
        if not self.colour_tau or labs is None:
            return None
        return np.linalg.norm(labs[:, None, :] - labs[None, :, :], axis=2) >= self.colour_tau

    def fuse(self, S, labs):
        """Fusion cosinus + couleur (beta > 0) pour une matrice carree S, labs : (n, 3) couleurs Lab des pieces."""
        return S if (self.beta <= 0 or labs is None) else fuse_colour(S, labs, labs, self.beta)

    def similarity(self, E: np.ndarray, items=None) -> np.ndarray:
        S = E @ E.T
        if self.beta > 0 and items is not None:
            if all("lab" in it for it in items):
                S = self.fuse(S, np.array([it["lab"] for it in items], float))
            elif all("hex" in it for it in items):
                rgb = np.array([[int(it["hex"][k:k + 2], 16) for k in (1, 3, 5)] for it in items], float)
                S = self.fuse(S, rgb2lab(rgb / 255.0))
        return S

    def _groups(self, S, cats, thr, same_category=True, extra_edges=(), block=None):
        A = (S >= thr)
        if same_category:
            A &= (cats[:, None] == cats[None, :])
        if block is not None:                             # meme coupe mais couleur nettement differente : jamais un doublon automatique
            A &= ~block
        for i, j in extra_edges:                          # paires de la zone grise confirmees « redondantes » par l'utilisatrice
            A[i, j] = A[j, i] = True
        np.fill_diagonal(A, False)
        return connected_components(A.astype(int), directed=False)[1]

    def level_of(self, score100: float) -> str:
        return "sain" if score100 < self.sain_max else ("quelques redondances" if score100 < self.modere_max else "fort encombrement")

    def zone_of(self, s: float) -> str:
        """Zone du score : DISTINCT < T_SIM <= SIMILAR < T_GRISE <= TO_CONFIRM < T_DUP <= DUPLICATE."""
        return "DUPLICATE" if s >= self.t_dup else "TO_CONFIRM" if s >= self.t_grise else "SIMILAR" if s >= self.t_sim else "DISTINCT"

    # ---- fonctions publiques ------------------------------------------------------------------------
    def purchase_check(self, cand_embedding, cand_category, E, cats, cand_lab=None, labs=None):
        """Verdict DOUBLON / A_CONFIRMER / SIMILAIRE / NOUVEAU : plus proche article de la MEME categorie (jamais une jupe contre un pantalon).
        A_CONFIRMER = zone grise : on pose la question fixe QUESTION a l'utilisatrice."""
        c = _normalise(np.asarray(cand_embedding)[None])[0]
        cos = E @ c
        if self.beta > 0 and cand_lab is not None and labs is not None:      # meme fusion cosinus + couleur que pour la garde-robe
            cos = fuse_colour(cos[None], np.asarray(cand_lab)[None], labs, self.beta)[0]
        s = np.where(np.asarray(cats) == cand_category, cos, -1.0)
        if len(s) == 0 or s.max() < -0.5:
            return {"verdict": "NOUVEAU", "nearest_index": None, "similarity": None}
        j = int(np.argmax(s))
        v = {"DUPLICATE": "DOUBLON", "TO_CONFIRM": "A_CONFIRMER", "SIMILAR": "SIMILAIRE", "DISTINCT": "NOUVEAU"}[self.zone_of(float(s[j]))]
        out = {"verdict": v, "nearest_index": j, "similarity": round(float(s[j]), 4)}
        if v == "DOUBLON" and self.colour_tau and cand_lab is not None and labs is not None \
                and float(np.linalg.norm(np.asarray(cand_lab, float) - np.asarray(labs, float)[j])) >= self.colour_tau:
            v = out["verdict"] = "A_CONFIRMER"             # meme coupe, couleur nettement differente : on demande
            out["reason"] = "colour"
        if v == "A_CONFIRMER":
            out["question"] = QUESTION
        return out

    def colour_map(self, groups, colours):
        obs = pd.crosstab(pd.Series(groups, name="groupe"), pd.Series(colours, name="couleur")) \
            .reindex(index=self.ref.index, columns=self.colours, fill_value=0)
        N = int(obs.values.sum())
        expected = self.ref.values * N
        pval = poisson.sf(obs.values - 1, expected)
        flag = (pval < self.alpha) & (obs.values >= MIN_CELL_COUNT)
        cells = [dict(group=obs.index[i], colour=obs.columns[j], observed=int(obs.values[i, j]),
                      expected=round(float(expected[i, j]), 2), p_value=float(pval[i, j]))
                 for i, j in zip(*np.where(flag))]
        allc = [dict(group=obs.index[i], colour=obs.columns[j], observed=int(obs.values[i, j]), expected=round(float(expected[i, j]), 2),
                     flagged=bool(flag[i, j])) for i, j in zip(*np.where(obs.values > 0))]        # toutes les cases non vides : pour dessiner la carte
        return {"n_items": N, "flagged": sorted(cells, key=lambda c: c["p_value"]), "cells": allc,
                "groups": [str(g) for g in obs.index], "palette": [str(c) for c in obs.columns]}

    def analyse_wardrobe(self, items, candidate=None, same_category=True, answers=None):
        """answers : reponses de l'utilisatrice a la question de la zone grise, [{"a": id, "b": id, "redundant": bool}, ...]."""
        warnings = []
        n = len(items)
        if n == 0:
            return {"n_items": 0, "warnings": ["garde-robe vide"]}
        if n < 20:
            warnings.append("moins de 20 articles : score d'encombrement non valide (valide sur ~40 articles)")
        if n < 30:
            warnings.append("moins de 30 articles : la carte ne detecte que de fortes concentrations")
        E = self._embeddings(items)
        cats = np.array([it["category"] for it in items], dtype=object)
        ids = [it["item_id"] for it in items]
        S = self.similarity(E, items)
        pos = {iid: k for k, iid in enumerate(ids)}
        answered = {frozenset((x["a"], x["b"])): bool(x["redundant"]) for x in (answers or []) if x["a"] in pos and x["b"] in pos and x["a"] != x["b"]}
        edges = [(pos[a], pos[b]) for p, yes in answered.items() if yes for a, b in [tuple(p)]]
        labs_ = self._labs(items)
        veto = self._colour_veto(labs_)
        lab = self._groups(S, cats, self.t_dup, same_category, edges, block=veto)
        sizes = np.bincount(lab)
        v0 = float((sizes - 1).sum() / n)
        score = int(round(100 * v0))
        groups = []
        for c in np.where(sizes > 1)[0]:
            idx = np.where(lab == c)[0]
            sub = S[np.ix_(idx, idx)]
            groups.append({"category": str(cats[idx[0]]), "item_ids": [ids[i] for i in idx],
                           "max_similarity": round(float(sub[np.triu_indices(len(idx), 1)].max()), 4)})
        # zone grise : paires de MEME categorie entre T_GRISE et T_DUP, pas encore repondues -> on pose la question
        same = (cats[:, None] == cats[None, :]) if same_category else np.ones_like(S, dtype=bool)
        grey = (S >= self.t_grise) & (S < self.t_dup)
        vetoed = (S >= self.t_dup) & veto if veto is not None else np.zeros_like(grey)       # doublons rabaisses a "a confirmer" par la couleur
        gi, gj = np.where(np.triu((grey | vetoed) & same, 1))
        to_confirm = [dict({"item_ids": [ids[i], ids[j]], "category": str(cats[i]), "similarity": round(float(S[i, j]), 4)}, **({"reason": "colour"} if vetoed[i, j] else {}))
                      for i, j in zip(gi, gj) if frozenset((ids[i], ids[j])) not in answered and lab[i] != lab[j]]      # deja dans le meme groupe (par chaine A~B, B~C) : pas de question
        to_confirm.sort(key=lambda d: -d["similarity"])
        si, sj = np.where(np.triu((S >= self.t_sim) & (S < self.t_grise) & same, 1))
        by_cat = []
        for t in sorted(set(cats)):
            idx = np.where(cats == t)[0]
            extra = sum(max(int((lab[idx] == c).sum()) - 1, 0) for c in np.unique(lab[idx]))
            by_cat.append({"category": str(t), "items": int(len(idx)), "extra": int(extra), "score100": int(round(100 * extra / len(idx)))})
        by_cat.sort(key=lambda d: -d["score100"])
        known = [it for it in items if it.get("colour") in self.colours and self.group_of(it["category"])]
        if len(known) < n:
            warnings.append(f"{n - len(known)} article(s) sans couleur de la palette ou categorie hors groupes : exclus de la carte")
        cmap = self.colour_map([self.group_of(it["category"]) for it in known], [it["colour"] for it in known]) if known else {"n_items": 0, "flagged": []}
        out = {"n_items": n,
               "duplicate_groups": groups,
               "clutter": {"score100": score, "level": self.level_of(score), "by_category": by_cat},
               "colour_map": cmap,
               "purchase_check": None,
               "to_confirm": to_confirm, "question": QUESTION, "n_similar_pairs": int(len(si)),
               "thresholds": {"model": self.model, "T_DUP": round(self.t_dup, 4), "T_SIM": round(self.t_sim, 4), "T_GRISE": round(self.t_grise, 4), "T_GRISE_source": self.grise_source, "beta": self.beta, "colour_tau": self.colour_tau,
                              "source": self.threshold_source,
                              "levels": {"sain_max": self.sain_max, "modere_max": self.modere_max}},
               "warnings": warnings}
        if candidate is not None:
            ce = candidate["embedding"] if "embedding" in candidate else self._embeddings([candidate])[0]
            r = self.purchase_check(ce, candidate["category"], E, cats, candidate.get("lab"), labs_)
            if r["nearest_index"] is not None:
                r["nearest_item_id"] = ids[r["nearest_index"]]
            out["purchase_check"] = r
        return out
