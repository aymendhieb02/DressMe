"""Calibre T_DUP / T_SIM / T_GRISE sur le catalogue de l'appli DressMe avec FashionCLIP (a lancer UNE FOIS, depuis la racine du depot).

    python bo3/calibrate_bo3.py            # 100 doublons fabriques
    python bo3/calibrate_bo3.py --n 150
    python bo3/calibrate_bo3.py --sweep    # compare plusieurs poids de couleur (beta), sans rien ecrire

Meme methode que le notebook BO3 : on fabrique des quasi-doublons (recadrage, rotation, luminosite, miroir), on mesure leur cosinus
avec l'original (positifs) et celui de paires aleatoires du catalogue (negatifs), puis T_DUP = meilleur F1, T_SIM = 99e percentile
des negatifs, T_GRISE = meme position relative que dans l'etude (pas d'annotations humaines pour ce catalogue).
Les embeddings FashionCLIP (Marqo) de tout le catalogue sont recalcules et ecrits dans data/bo3_emb.npy : le moteur BO3 les utilise.
Ecrit data/bo3_thresholds.json, avec des controles (rappel sur les doublons fabriques, part des paires de meme type par zone).
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bo3.bo3_service import MAX_COLOUR_TAU, SIGMA_COLOUR, calibrate_thresholds, colour_lab, fuse_colour, grise_from


def make_variant(img, rng):
    w, h = img.size
    s = rng.uniform(0.85, 1.0); cw, ch = int(w * s), int(h * s)
    x0 = int(rng.integers(0, w - cw + 1)); y0 = int(rng.integers(0, h - ch + 1))
    img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h))
    img = img.rotate(float(rng.uniform(-8, 8)), resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    img = ImageEnhance.Brightness(img).enhance(float(rng.uniform(0.85, 1.15)))
    img = ImageEnhance.Color(img).enhance(float(rng.uniform(0.9, 1.1)))
    return ImageOps.mirror(img) if rng.random() < 0.3 else img


def calibrate(images, encode, bytype_idx, n_aug=100, n_neg=5000, seed=42, beta=0.0):
    """images : liste d'images PIL du catalogue ; encode(list[PIL]) -> embeddings normalises (n, d) ; bytype_idx : {type: [indices]}.
    beta > 0 : similarite fusionnee (1 - beta) * cosinus + beta * exp(-deltaE / sigma), couleur lue sur les pixels (comme le notebook)."""
    rng = np.random.default_rng(seed)
    E = np.vstack([encode(images[s:s + 32]) for s in range(0, len(images), 32)]).astype(np.float32)
    L = np.array([colour_lab(im) for im in images], dtype=np.float32)
    src = rng.choice(len(images), size=min(n_aug, len(images)), replace=False)
    variants = [make_variant(images[i], rng) for i in src]
    aug = np.vstack([encode(variants[s:s + 32]) for s in range(0, len(variants), 32)])
    pos = (aug * E[src]).sum(1)
    dE = np.linalg.norm(np.array([colour_lab(v) for v in variants]) - L[src], axis=1)     # ecart de couleur cree par l'eclairage/le recadrage seuls
    tau_p99 = float(np.percentile(dE, 99))                 # ecart de couleur que l'eclairage/le recadrage seuls peuvent creer
    colour_tau = min(max(10.0, tau_p99), MAX_COLOUR_TAU)   # au-dela : couleur nettement differente ; plafonne pour que la regle reste active
    if beta > 0:
        pos = (1 - beta) * pos + beta * np.exp(-dE / SIGMA_COLOUR)
    n = len(images); i = rng.integers(0, n, n_neg); j = rng.integers(0, n, n_neg); k = i != j
    neg = (E[i[k]] * E[j[k]]).sum(1)                       # paires aleatoires de tout type, comme le notebook
    if beta > 0:
        neg = (1 - beta) * neg + beta * np.exp(-np.linalg.norm(L[i[k]] - L[j[k]], axis=1) / SIGMA_COLOUR)
    t_dup, t_sim, f1 = calibrate_thresholds(pos, neg)
    t_grise = grise_from(t_sim, t_dup)
    S = fuse_colour(E @ E.T, L, L, beta) if beta > 0 else E @ E.T
    same = np.array([float(x) for idx in bytype_idx.values() if len(idx) > 1 for x in S[np.ix_(idx, idx)][np.triu_indices(len(idx), 1)]])
    checks = dict(recall_doublons_fabriques=round(float((pos >= t_dup).mean()), 3),
                  meme_type_doublon=round(float((same >= t_dup).mean()), 3),
                  meme_type_zone_grise=round(float(((same >= t_grise) & (same < t_dup)).mean()), 3),
                  meme_type_similaire=round(float(((same >= t_sim) & (same < t_grise)).mean()), 3), n_paires_meme_type=int(len(same)))
    return E, L, dict(T_DUP=round(t_dup, 4), T_SIM=round(t_sim, 4), T_GRISE=round(t_grise, 4), F1=round(f1, 3), n_positifs=int(len(pos)), n_negatifs=int(k.sum()),
                      model="fashionclip", beta=beta, sigma_colour=SIGMA_COLOUR, colour_tau=round(colour_tau, 1), colour_tau_p99=round(tau_p99, 1), checks=checks)


def sweep(images, encode, bytype_idx, betas=(0.0, 0.05, 0.10, 0.15), **kw):
    """Compare plusieurs poids de couleur sur les MEMES doublons fabriques et les MEMES paires aleatoires (embeddings calcules une seule fois).
    N'ecrit aucun fichier. Retourne {beta: sortie de calibrate()}."""
    cache = {}
    def cached(ims):
        keys = [(im.size, hash(im.tobytes())) for im in ims]
        miss = [i for i, k in enumerate(keys) if k not in cache]
        if miss:
            for i, v in zip(miss, encode([ims[i] for i in miss])):
                cache[keys[i]] = v
        return np.stack([cache[k] for k in keys])
    return {b: calibrate(images, cached, bytype_idx, beta=b, **kw)[2] for b in betas}


def print_sweep(res):
    print(f"{'beta':>5} {'F1':>6} {'rappel':>7} {'T_SIM':>7} {'T_GRISE':>8} {'T_DUP':>7} {'doublon':>8} {'a confirmer':>12} {'similaire':>10}   (parts des paires de meme type)")
    for b, o in res.items():
        c = o["checks"]
        print(f"{b:5.2f} {o['F1']:6.3f} {c['recall_doublons_fabriques']:7.2f} {o['T_SIM']:7.4f} {o['T_GRISE']:8.4f} {o['T_DUP']:7.4f} {c['meme_type_doublon']:8.1%} {c['meme_type_zone_grise']:12.1%} {c['meme_type_similaire']:10.1%}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=100); ap.add_argument("--seed", type=int, default=42); ap.add_argument("--beta", type=float, default=0.0, help="poids de la couleur dans la similarite (0 = couleur ignoree)")
    ap.add_argument("--sweep", action="store_true", help="compare beta = 0, 0.05, 0.10, 0.15 sans rien ecrire (embeddings calcules une fois)")
    A = ap.parse_args()
    import torch, open_clip, api, redundancy               # api : memes donnees que l'appli
    model, _, pre = open_clip.create_model_and_transforms("hf-hub:Marqo/marqo-fashionCLIP"); model.eval()    # meme modele que similar.py et que l'etude
    def encode(ims):
        with torch.no_grad():
            return torch.nn.functional.normalize(model.encode_image(torch.stack([pre(i) for i in ims])).float(), dim=-1).numpy()
    images = [Image.open(api.DATA / "img" / f"{c}.jpg").convert("RGB") for c in api.CODES]
    if A.sweep:
        print_sweep(sweep(images, encode, redundancy.bytype(), n_aug=A.n, seed=A.seed)); print("\nRien n'a ete ecrit. Pour appliquer un choix : python bo3\\calibrate_bo3.py --beta <valeur>"); return
    E, L, out = calibrate(images, encode, redundancy.bytype(), A.n, seed=A.seed, beta=A.beta)
    out["source"] = f"calibrated on this catalogue with FashionCLIP ({out['n_positifs']} synthetic duplicates, seed {A.seed})"
    out["T_GRISE_note"] = "provisoire : meme position relative entre T_SIM et T_DUP que dans l'etude (pas d'annotations humaines pour ce catalogue)"
    np.save(api.DATA / "bo3_emb.npy", E.astype("float32")); np.save(api.DATA / "bo3_colour_lab.npy", L.astype("float32"))
    (api.DATA / "bo3_thresholds.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    c = out["checks"]
    if out["F1"] < 0.6 or c["recall_doublons_fabriques"] < 0.8 or c["meme_type_doublon"] > 0.25:
        print("\nATTENTION : calibration peu fiable (F1 < 0.6, rappel < 0.8 ou plus de 25 % des paires de meme type en doublon). Ne pas s'y fier ; envoie cette sortie.")
    if out["colour_tau_p99"] > MAX_COLOUR_TAU:
        print(f"\nATTENTION : la couleur lue sur les pixels est instable (99e percentile de l'ecart sur les doublons fabriques = {out['colour_tau_p99']}, plafonne a {MAX_COLOUR_TAU}). La regle de couleur est a verifier a l'oeil.")
    print("\necrit :", api.DATA / "bo3_thresholds.json", "et", api.DATA / "bo3_emb.npy", "et", api.DATA / "bo3_colour_lab.npy", "\nRelance l'API pour appliquer les seuils.")


if __name__ == "__main__":
    main()
