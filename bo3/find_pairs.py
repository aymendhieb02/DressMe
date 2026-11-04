"""Liste les paires de pieces les plus proches du catalogue de l'appli (meme categorie) pour tester la detection de doublons.

    python bo3/find_pairs.py            # 30 paires
    python bo3/find_pairs.py --top 60
    python bo3/find_pairs.py --zone grise     # seulement la zone grise (a confirmer) : les paires qui declenchent la question

Test dans l'appli : copie une ligne "console" affichee, colle-la dans la console du navigateur (F12) sur la page Wardrobe Check,
puis clique "Check my wardrobe" : la paire apparait dans "To confirm" avec la question.

Pour chaque paire : similarite, verdict avec les seuils actuels (DOUBLON / SIMILAIRE / sous le seuil), indices et descriptions.
Ecrit aussi bo3/pairs_to_review.csv. Dans la page Wardrobe Check : "+ Add a piece" puis cherche la description,
ou colle les deux indices dans la console du navigateur : RD.items=[C[i],C[j]];rdDraw(null)
"""
import argparse, csv, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--top", type=int, default=30); ap.add_argument("--zone", choices=["all", "grise", "doublon", "similaire"], default="all"); A = ap.parse_args(argv); n = A.top
    import api, redundancy
    e = redundancy.engine()
    SM = redundancy.sim_matrix()
    pairs = []
    for c, idx in redundancy.bytype().items():
        if len(idx) < 2: continue
        S = SM[np.ix_(idx, idx)]
        for x, y in zip(*np.triu_indices(len(idx), 1)): pairs.append((float(S[x, y]), idx[x], idx[y], c))
    pairs.sort(reverse=True)  # type = categorie affinee par la description (ex. top/T-shirts)
    NAME = {"DUPLICATE": "DOUBLON", "TO_CONFIRM": "ZONE GRISE", "SIMILAR": "SIMILAIRE", "DISTINCT": "sous le seuil"}
    verdict = lambda s: NAME[e.zone_of(s)]
    print(f"Seuils : doublon >= {e.t_dup:.3f}, zone grise >= {e.t_grise:.3f}, similaire >= {e.t_sim:.3f}  ({e.threshold_source})")
    print(f"Paires de meme type : {len(pairs)} ; doublon : {sum(p[0] >= e.t_dup for p in pairs)} ; zone grise : {sum(e.t_grise <= p[0] < e.t_dup for p in pairs)} ; similaire : {sum(e.t_sim <= p[0] < e.t_grise for p in pairs)}\n")
    want = {"all": None, "grise": "ZONE GRISE", "doublon": "DOUBLON", "similaire": "SIMILAIRE"}[A.zone]
    if want: pairs = [p for p in pairs if verdict(p[0]) == want]
    rows = []
    for s, i, j, c in pairs[:n]:
        rows.append(dict(sim=round(s, 4), verdict=verdict(s), cat=c, i=i, j=j, desc_i=api.DESC[i], desc_j=api.DESC[j]))
        print(f"{s:.3f}  {verdict(s):13s} [{c}] {i:3d} {api.DESC[i][:38]:38s} | {j:3d} {api.DESC[j][:38]}")
        print(f"        console : RD.items=[C[{i}],C[{j}]];rdDraw(null)")
    if not rows: sys.exit("Aucune paire dans cette zone pour ce catalogue.")
    out = Path(__file__).parent / "pairs_to_review.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("\necrit :", out)
    return rows


if __name__ == "__main__":
    main()
