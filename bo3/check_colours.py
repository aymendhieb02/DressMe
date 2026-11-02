"""Compare la couleur lue sur les pixels a celle de la description du catalogue (a lancer depuis la racine de l'appli).

    python bo3/check_colours.py

Affiche le taux d'accord par couleur et la liste des desaccords (les plus utiles pour juger si la lecture sur les pixels est fiable). Ne modifie rien.
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bo3.bo3_service import colour_lab, rgb2lab

PROTOTYPES = {"black": (25, 25, 25), "white": (245, 245, 245), "grey": (128, 128, 128), "beige": (222, 200, 165), "brown": (110, 70, 40),
              "blue": (60, 90, 160), "burgundy": (110, 20, 40), "pink": (240, 170, 190), "red": (190, 30, 40), "green": (60, 110, 60)}
NAVY = (25, 35, 80)      # un bleu tres sombre est lu comme "blue" (la palette de l'appli n'a pas de navy)


def nearest_colour(lab):
    best, bd = None, 1e9
    for name, rgb in list(PROTOTYPES.items()) + [("blue", NAVY)]:
        d = float(np.linalg.norm(lab - rgb2lab(np.array(rgb) / 255.0)))
        if d < bd: best, bd = name, d
    return best


def agreement(labs, descr_colours):
    """[(indice, couleur description, couleur pixels)] pour les pieces dont la description a une couleur de la palette."""
    return [(i, c, nearest_colour(l)) for i, (l, c) in enumerate(zip(labs, descr_colours)) if c is not None]


def main():
    import api, redundancy
    images = [Image.open(api.DATA / "img" / f"{c}.jpg").convert("RGB") for c in api.CODES]
    labs = np.array([colour_lab(im) for im in images])
    rows = agreement(labs, [redundancy.colour_of(d) for d in api.DESC])
    ok = [r for r in rows if r[1] == r[2]]
    print(f"Accord pixels / description : {len(ok)} sur {len(rows)} pieces ({len(ok) / max(len(rows), 1):.0%})\n")
    print("Desaccords (piece, description, pixels) :")
    for i, c, p in rows:
        if c != p: print(f"  {i:4d}  {c:9s} {p:9s}  {api.DESC[i][:70]}")


if __name__ == "__main__":
    main()
