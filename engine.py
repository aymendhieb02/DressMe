import numpy as np, pandas as pd
from dataclasses import dataclass, field

STYLES = ["casual", "sportswear", "streetwear", "formel", "soiree", "chic", "boheme",
          "minimaliste", "vintage", "ethnique", "preppy", "romantique", "rock"]
CLOTHING = {"haut", "bas", "robe", "veste", "ensemble"}
START_SLOTS = CLOTHING | {"chaussures"}


@dataclass
class UserState:
    gender: str = "all"                                   # "Men", "Women" ou "all"
    liked: list = field(default_factory=list)             # indices de lignes du catalogue
    disliked: list = field(default_factory=list)
    saved: list = field(default_factory=list)
    seen: set = field(default_factory=set)

    @property
    def n_react(self):
        return len(self.liked) + len(self.disliked)


class Engine:
    def __init__(self, cat, E, seed=0):
        self.cat = cat.reset_index(drop=True)
        E = np.asarray(E, np.float32)
        self.E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
        cols = [f"p_{s}" for s in STYLES if f"p_{s}" in self.cat.columns]
        self.P = self.cat[cols].fillna(0).to_numpy(np.float32)
        self.top1 = self.P.argmax(1)
        self.conf = self.P.max(1)
        self.slot = self.cat["slot"].to_numpy()
        g = self.cat["gender"].to_numpy()
        self._mask = {"Men": np.isin(g, ["Men", "Unisex"]),
                      "Women": np.isin(g, ["Women", "Unisex"]),
                      "all": np.ones(len(g), bool)}
        self.rng = np.random.default_rng(seed)

    def allowed(self, u):
        return self._mask.get(u.gender, self._mask["all"]).copy()

    def react(self, u, i, kind):
        u.seen.add(int(i))
        if kind == "like": u.liked.append(int(i))
        elif kind == "dislike": u.disliked.append(int(i))
        elif kind == "save": u.saved.append(int(i)); u.liked.append(int(i))

    def scores(self, u, k=3, beta=0.6, gamma=0.5):
        s = np.zeros(len(self.E), np.float32)
        sp = np.zeros(self.P.shape[1], np.float32)
        if u.liked:
            S = self.E @ self.E[u.liked].T
            s += np.sort(S, axis=1)[:, -min(k, S.shape[1]):].mean(1)
            sp += self.P[u.liked].mean(0)
        if u.disliked:
            S = self.E @ self.E[u.disliked].T
            s -= beta * np.sort(S, axis=1)[:, -min(k, S.shape[1]):].mean(1)
            sp -= beta * self.P[u.disliked].mean(0)
        return s + gamma * (self.P @ sp)

    def starter(self, u, n=24, slot=None):
        ok = self.allowed(u)
        ok[list(u.seen)] = False
        ok &= (self.slot == slot) if slot else np.isin(self.slot, list(START_SLOTS))
        idx = np.where(ok)[0]
        if not idx.size: return []
        pools = []
        for s in range(self.P.shape[1]):
            c = idx[self.top1[idx] == s]
            if c.size:
                c = c[self.conf[c] >= np.median(self.conf[c])]
                pools.append(list(self.rng.permutation(c)))
        self.rng.shuffle(pools)
        picks = []
        while len(picks) < n and any(pools):
            for p in pools:
                if p and len(picks) < n: picks.append(int(p.pop()))
        return picks

    def _mmr(self, cand, sc, n, lam):
        chosen, pool = [], list(range(len(cand)))
        while pool and len(chosen) < n:
            if chosen:
                red = (self.E[cand[pool]] @ self.E[cand[chosen]].T).max(1)
                j = int(np.argmax(sc[pool] - lam * red))
            else:
                j = int(np.argmax(sc[pool]))
            chosen.append(pool.pop(j))
        return [int(cand[j]) for j in chosen]

    def recommend(self, u, n=12, slot=None, explore=None, lam=0.3):
        if u.n_react == 0:
            return self.starter(u, n, slot)
        ok = self.allowed(u)
        ok[list(u.seen)] = False
        if slot: ok &= (self.slot == slot)
        idx = np.where(ok)[0]
        if not idx.size: return []
        if explore is None:
            explore = max(0.1, 0.5 / (1 + u.n_react / 8))
        n_exp = min(n, int(round(n * explore)))
        sc = self.scores(u)
        top = idx[np.argsort(-sc[idx])[:200]]
        picks = self._mmr(top, sc[top], n - n_exp, lam)
        rest = np.setdiff1d(idx, picks)
        exp = self.rng.choice(rest, min(n_exp, rest.size), replace=False).tolist() if rest.size else []
        return picks + [int(x) for x in exp]
