"""Quelles pieces font exploser l'ecart de couleur des doublons fabriques ? (a lancer depuis la racine de l'appli)

    python bo3/diagnose_colour.py            # les 12 pires pieces

Rejoue les MEMES variantes que calibrate_bo3.py (meme graine) et affiche, pour les pires : code, description, couleur Lab de l'original et de la variante,
ecart de couleur. N'ecrit rien dans data/ ; ecrit bo3/colour_diagnosis/*.png (original | variante) pour regarder a l'oeil.
"""
import argparse, sys
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bo3.bo3_service import colour_lab
from bo3.calibrate_bo3 import make_variant


def worst_variants(images, n_aug=100, seed=42, top=12):
    """Meme tirage que calibrate() : renvoie [(indice, ecart, lab_original, lab_variante, variante)] trie par ecart decroissant."""
    rng = np.random.default_rng(seed)
    src = rng.choice(len(images), size=min(n_aug, len(images)), replace=False)
    variants = [make_variant(images[i], rng) for i in src]
    out = []
    for i, v in zip(src, variants):
        lo, lv = colour_lab(images[i]), colour_lab(v)
        out.append((int(i), float(np.linalg.norm(lo - lv)), lo, lv, v))
    out.sort(key=lambda t: -t[1])
    return out[:top]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=100); ap.add_argument("--seed", type=int, default=42); ap.add_argument("--top", type=int, default=12)
    A = ap.parse_args()
    import api
    images = [Image.open(api.DATA / "img" / f"{c}.jpg").convert("RGB") for c in api.CODES]
    outdir = Path(__file__).parent / "colour_diagnosis"; outdir.mkdir(exist_ok=True)
    print(f"{'rang':>4} {'piece':>5} {'ecart':>6}  {'L,a,b original':>20}  {'L,a,b variante':>20}  description")
    for r, (i, d, lo, lv, v) in enumerate(worst_variants(images, A.n, A.seed, A.top), 1):
        print(f"{r:4d} {i:5d} {d:6.1f}  {np.array2string(lo, precision=0, floatmode='fixed'):>20}  {np.array2string(lv, precision=0, floatmode='fixed'):>20}  {api.DESC[i][:60]}")
        w = Image.new("RGB", (512, 256), (255, 255, 255)); w.paste(images[i].resize((256, 256)), (0, 0)); w.paste(v.resize((256, 256)), (256, 0)); w.save(outdir / f"{r:02d}_piece{i}.png")
    print(f"\nImages (original | variante) : {outdir}")


if __name__ == "__main__":
    main()
