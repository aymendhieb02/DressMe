# Depuis la racine :  python -m scripts.build_gender
import csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import api
import wardrobe as W

DS = ROOT / "data" / "garment2look"
OUT = ROOT / "data" / "catalog_gender.json"
IMG_RE = re.compile(r"[^\s,;|\[\]\"']+\.(?:jpe?g|png|webp)", re.I)
MARGIN = 0.015          # écart de similarité sous lequel la pièce est considérée unisexe


def find_img(name):
    for p in (DS / name, DS / "images" / name, DS / "images" / Path(name).name):
        if p.is_file():
            return p
    return None


def images_of(gender):
    found = {}
    with open(DS / f"garment2look_{gender}.csv", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for cell in row.values():
                for name in IMG_RE.findall(str(cell or "")):
                    p = find_img(name)
                    if p:
                        found[p.name] = p
    return found


def embed(paths):
    out = []
    for n, p in enumerate(paths):
        try:
            out.append(W.enc_image(api, p.read_bytes()))
        except Exception:
            continue
        if n % 200 == 0:
            print(f"  {n}/{len(paths)}")
    return np.stack(out)


if __name__ == "__main__":
    fw, fm = images_of("women"), images_of("men")
    shared = set(fw) & set(fm)                       # image présente dans les deux CSV = ambiguë
    pw = [p for k, p in fw.items() if k not in shared]
    pm = [p for k, p in fm.items() if k not in shared]
    print(f"women: {len(pw)} images | men: {len(pm)} images | ignorées (communes): {len(shared)}")
    if not pw or not pm:
        sys.exit("Aucune image trouvée : vérifie data/garment2look/ (CSV + dossier images).")

    print("Embedding women..."); Ew = embed(pw)
    print("Embedding men...");   Em = embed(pm)

    sw = (api.EMB @ Ew.T).max(1)                     # similarité max de chaque pièce du catalogue à une image femme
    sm = (api.EMB @ Em.T).max(1)                     # ... à une image homme
    women, men = [], []
    for i in range(len(api.CAT)):
        d = float(sw[i] - sm[i])
        if api.CAT[i] == "dress":                    # robe = toujours femme
            women.append(i)
        elif d > MARGIN:
            women.append(i)
        elif d < -MARGIN:
            men.append(i)
        else:                                        # unisexe : disponible pour les deux
            women.append(i); men.append(i)

    OUT.write_text(json.dumps({"women": women, "men": men}), encoding="utf-8")
    from collections import Counter
    print("catalogue:", len(api.CAT))
    print("women:", len(women), dict(Counter(api.CAT[i] for i in women)))
    print("men:  ", len(men), dict(Counter(api.CAT[i] for i in men)))
    print("écrit:", OUT)