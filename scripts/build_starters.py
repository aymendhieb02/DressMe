# Depuis la racine du projet :  python -m scripts.build_starters
import csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import api                      # charge CLIP + catalogue
import wardrobe as W            # adapte le nom si ton fichier s'appelle autrement

DS = ROOT / "data" / "garment2look"
OUT = ROOT / "data" / "starter_wardrobes.json"
IMG_RE = re.compile(r"[^\s,;|\[\]\"']+\.(?:jpe?g|png|webp)", re.I)
MAX_PIECES = 5
_cache = {}


def find_img(name):
    for p in (DS / name, DS / "images" / name, DS / "images" / Path(name).name):
        if p.is_file():
            return p
    return None


def to_catalog(path, men, names, T, ok):
    """Photo du dataset -> id de la pièce de catalogue la plus proche (dans la bonne catégorie)."""
    if path in _cache:
        return _cache[path]
    v = W.enc_image(api, path.read_bytes())
    k = int((T[ok] @ v).argmax())
    cat = names[ok[k]]
    idx = list(api.BYCAT.get(cat, []))
    res = None
    if idx and cat != "other":
        res = idx[int(np.argmax(api.EMB[idx] @ v))]
    _cache[path] = res
    return res


def build(gender):
    men = gender == "men"
    names, T = W.cat_text_matrix()
    ok = [k for k, c in enumerate(names) if not (men and c == "dress")]
    csv_path = DS / f"garment2look_{gender}.csv"
    outfits, rows_n, imgs_n = [], 0, 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for row in rd:
            rows_n += 1
            if rows_n == 1:
                print(f"[{gender}] colonnes:", rd.fieldnames, "\n   1re ligne:", dict(list(row.items())[:6]))
            ids = []
            for cell in row.values():
                for name in IMG_RE.findall(str(cell or "")):
                    p = find_img(name)
                    if not p:
                        continue
                    imgs_n += 1
                    i = to_catalog(p, men, names, T, ok)
                    if i is not None and i not in ids and len(ids) < MAX_PIECES:
                        ids.append(i)
            if len(ids) >= 2:
                outfits.append(ids)
    print(f"[{gender}] {rows_n} lignes, {imgs_n} images trouvées, {len(outfits)} tenues utilisables")
    return outfits


if __name__ == "__main__":
    data = {g: build(g) for g in ("women", "men")}
    OUT.write_text(json.dumps(data), encoding="utf-8")
    print("écrit:", OUT)