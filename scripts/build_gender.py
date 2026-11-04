"""
Génère data/catalog_gender.json : quelles pièces du catalogue sont "women" et "men".
 
Utilise directement tes deux dossiers :
    data/images/women/...
    data/images/men/...
(les CSV ne sont pas nécessaires)
 
Lancer depuis la racine du projet :
    .\.venv-app\Scripts\python.exe -m scripts.build_gender
Puis REDÉMARRER le serveur.
"""
import json
import random
import sys
from pathlib import Path
 
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
 
import numpy as np
 
import api                 # charge CLIP + catalogue
import wardrobe as W
 
DATA = ROOT / "data"
DIRS = {"women": DATA / "images" / "women", "men": DATA / "images" / "men"}
OUT = DATA / "catalog_gender.json"
EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PER_GENDER = 600       # images utilisées par genre (suffisant, et rapide sur CPU)
 
 
def list_images(folder):
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in EXT]
    random.Random(0).shuffle(files)
    return files[:MAX_PER_GENDER]
 
 
def embed(files, label):
    out = []
    for n, p in enumerate(files, 1):
        try:
            out.append(W.enc_image(api, p.read_bytes()))
        except Exception:
            continue
        if n % 100 == 0:
            print(f"  {label}: {n}/{len(files)}")
    return np.stack(out) if out else None
 
 
if __name__ == "__main__":
    for g, d in DIRS.items():
        if not d.is_dir():
            sys.exit(f"Dossier introuvable : {d}")
 
    fw, fm = list_images(DIRS["women"]), list_images(DIRS["men"])
    print(f"images women: {len(fw)} | images men: {len(fm)}")
    if not fw or not fm:
        sys.exit("Aucune image trouvée dans data/images/women ou data/images/men.")
 
    print("Embedding women...")
    Ew = embed(fw, "women")
    print("Embedding men...")
    Em = embed(fm, "men")
    if Ew is None or Em is None:
        sys.exit("Impossible de lire les images.")
 
    split, d = W.split_by_gender(api, Ew, Em)
    OUT.write_text(json.dumps(split), encoding="utf-8")
 
    sw, sm = set(split["women"]), set(split["men"])
    print(f"\ncatalogue: {len(api.CAT)} pièces")
    print(f"{'catégorie':10} {'femme seule':>12} {'homme seul':>11} {'les deux':>9}")
    for c in sorted({str(x) for x in api.CAT}):
        ids = [i for i in range(len(api.CAT)) if str(api.CAT[i]) == c]
        both = sum(1 for i in ids if i in sw and i in sm)
        print(f"{c:10} {sum(1 for i in ids if i in sw and i not in sm):>12} "
              f"{sum(1 for i in ids if i in sm and i not in sw):>11} {both:>9}")
    print("\nécrit:", OUT)
    print("Redémarre le serveur pour que le filtre soit pris en compte.")
 