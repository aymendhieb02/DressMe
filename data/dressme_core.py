"""dressme_core : code PARTAGE entre le notebook d'entrainement et l'interface.
Le notebook ecrit ce fichier, l'interface l'importe : meme code des deux cotes."""
import re, json
import torch, torch.nn as nn, torch.nn.functional as F

K = 5                                   # max d'articles : 4 vetements + 1 accessoire
ACC_CATS = {"accessory", "bag"}         # categories comptees comme "accessoire" (5e slot)
DEFAULT_THR = {"p_odd": 0.5, "delta": -0.5}

# ----------------------------------------------------------------------------------------
# 1) CATEGORIES : on cherche le NOM PRINCIPAL = dernier mot reconnu de la description
#    ("knit midi skirt" -> skirt ; "baggy jeans" -> jeans ; "leather belt bag" -> bag)
# ----------------------------------------------------------------------------------------
CAT_WORDS = {
    "shoes": "sneaker boot bootie sandal loafer pump heel flat mule shoe slipper slide oxford derby "
             "espadrille trainer wedge clog slingback moccasin".split(),
    "bag": "bag handbag tote clutch backpack purse pouch satchel crossbody".split(),
    "dress": "dress gown jumpsuit playsuit kaftan caftan".split(),
    "outer": "coat jacket blazer parka trench vest gilet cape poncho blouson bomber anorak overcoat "
             "puffer windbreaker".split(),
    "top": "t-shirt shirt blouse sweater top knit cardigan hoodie sweatshirt polo tank bodysuit jumper "
           "turtleneck tee camisole tunic pullover".split(),
    "bottom": "pant pants trouser trousers jean jeans skirt short shorts legging leggings jogger joggers "
              "sweatpant sweatpants chino chinos culotte culottes bermuda".split(),
    "accessory": "belt scarf hat sunglasses glasses glove cap beanie necklace bracelet earring ring watch "
                 "tie sock tights headband brooch bandana foulard shawl stole choker pendant anklet "
                 "cuff wallet".split(),
}
WORD2CAT = {w: c for c, ws in CAT_WORDS.items() for w in ws}


def category(desc):
    d = (desc or "").lower()
    d = re.split(r"\bwith\b|\bfeaturing\b|,|\(", d)[0] or d      # on coupe "... with leather trim"
    toks = re.findall(r"[a-z]+", d)
    for t in reversed(toks):
        for cand in (t, t[:-1] if t.endswith("s") else t, t[:-2] if t.endswith("es") else t):
            if cand in WORD2CAT:
                return WORD2CAT[cand]
    return "other"


# ----------------------------------------------------------------------------------------
# 2) SAISONS / STYLES NORMALISES ("Spring/Summer" == "Spring, Summer" ; "Smart Casual Style" ~ "Smart Casual")
# ----------------------------------------------------------------------------------------
def _as_text(x):
    if isinstance(x, (list, tuple)):
        return " ".join(map(str, x))
    return str(x or "")


def norm_season(s):
    s = _as_text(s).lower()
    out = set()
    if "spring" in s: out.add("spring")
    if "summer" in s: out.add("summer")
    if "autumn" in s or "fall" in s: out.add("autumn")
    if "winter" in s: out.add("winter")
    return frozenset(out)                      # vide = inconnu


def seasons_disjoint(a, b):                    # les deux connues ET aucune saison commune
    return bool(a) and bool(b) and not (a & b)


def seasons_compatible(a, b):                  # au moins une saison commune
    return bool(a & b)


def norm_style(s):
    toks = set(re.findall(r"[a-z]+", _as_text(s).lower())) - {"style", "other", "unknown"}
    return frozenset(toks)


def style_close(a, b):                         # Jaccard >= 0.5 -> meme style
    if not a or not b:
        return True                            # inconnu : on ne pretend pas qu'ils different
    return len(a & b) / len(a | b) >= 0.5


# ----------------------------------------------------------------------------------------
# 3) MODELE
# ----------------------------------------------------------------------------------------
class OutfitScorer(nn.Module):
    def __init__(self, visual, d=256, heads=4, layers=2):
        super().__init__()
        self.visual = visual
        self.proj = nn.Linear(512, d)
        self.cls = nn.Parameter(torch.randn(1, 1, d) * 0.02)
        layer = nn.TransformerEncoderLayer(d, heads, 4 * d, 0.1, batch_first=True)
        self.tf = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.score_head = nn.Linear(d, 1)
        self.none_head = nn.Linear(d, 1)
        self.odd_head = nn.Linear(d, 1)

    def encode_images(self, x):
        return F.normalize(self.visual(x).float(), dim=-1)

    def forward(self, emb, mask):              # emb (B,k,512) ; mask (B,k) vrai = article present
        B = emb.shape[0]
        x = torch.cat([self.cls.expand(B, -1, -1), self.proj(emb.float())], 1)
        pad = torch.cat([torch.zeros(B, 1, dtype=torch.bool, device=emb.device), ~mask], 1)
        h = self.tf(x, src_key_padding_mask=pad)
        score = 10 * torch.sigmoid(self.score_head(h[:, 0]).squeeze(-1))
        odd_items = self.odd_head(h[:, 1:]).squeeze(-1).masked_fill(~mask, -1e4)
        odd = torch.cat([self.none_head(h[:, 0]), odd_items], 1)       # (B, 1+k) ; 0 = aucun intrus
        return score, odd


@torch.no_grad()
def score_rows(model, E, rows, bs=256):
    """Note de chaque tenue. rows = liste de listes d'indices dans la table E (longueurs variables)."""
    model.eval(); dev = E.device; out = []
    for i in range(0, len(rows), bs):
        chunk = rows[i:i + bs]; kmax = max(len(r) for r in chunk)
        t = torch.zeros(len(chunk), kmax, dtype=torch.long, device=dev)
        m = torch.zeros(len(chunk), kmax, dtype=torch.bool, device=dev)
        for b, r in enumerate(chunk):
            t[b, :len(r)] = torch.tensor(r, device=dev); m[b, :len(r)] = True
        s, _ = model(E[t], m); out.append(s.cpu())
    return torch.cat(out) if out else torch.zeros(0)


# ----------------------------------------------------------------------------------------
# 4) VERIFICATION D'UN ACCESSOIRE : match ou non ?
# ----------------------------------------------------------------------------------------
@torch.no_grad()
def check_accessory(model, base_emb, acc_emb, thr=None):
    """base_emb (n,512) = vetements SANS accessoire (1 a 4) ; acc_emb (512,) = accessoire ajoute.
    Compare la tenue avec et sans l'accessoire.
      delta = note(avec) - note(sans) ; p_odd = proba que l'accessoire soit l'intrus.
    MATCH si p_odd < seuil ET delta > seuil ; NO MATCH si les deux signaux sont mauvais ; sinon BORDERLINE."""
    thr = thr or DEFAULT_THR
    n = int(base_emb.shape[0])
    if not 1 <= n <= K - 1:
        raise ValueError(f"Il faut entre 1 et {K - 1} vetements (recu {n}) + 1 accessoire.")
    model.eval(); dev = base_emb.device
    emb = torch.zeros(2, n + 1, base_emb.shape[1], device=dev)
    emb[:, :n] = base_emb.float(); emb[1, n] = acc_emb.float()
    mask = torch.ones(2, n + 1, dtype=torch.bool, device=dev); mask[0, n] = False
    sc, ol = model(emb, mask)
    p_odd = torch.softmax(ol[1], -1)[n + 1].item()           # indice 0 = "aucun intrus", puis 1 + position
    s_wo, s_with = sc[0].item(), sc[1].item()
    delta = s_with - s_wo
    ok_p, ok_d = p_odd < thr["p_odd"], delta > thr["delta"]
    verdict = "MATCH" if (ok_p and ok_d) else ("NO MATCH" if (not ok_p and not ok_d) else "BORDERLINE")
    return dict(verdict=verdict, match=bool(ok_p and ok_d), score_without=s_wo, score_with=s_with,
                delta=delta, p_odd=p_odd, base_ok=s_wo >= 5)


# ----------------------------------------------------------------------------------------
# 5) CHARGEMENT POUR L'INTERFACE
# ----------------------------------------------------------------------------------------
def load_scorer(path, device=None):
    """Recharge le modele exporte. Retourne (model, preprocess, config)."""
    import open_clip
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    cfg = json.load(open(f"{path}/config.json"))
    clip_model, _, preprocess = open_clip.create_model_and_transforms(cfg["clip_name"],
                                                                      pretrained=cfg["clip_pretrained"])
    visual = clip_model.visual; del clip_model
    visual.load_state_dict(torch.load(f"{path}/visual.pt", map_location="cpu"))      # CLIP FINE-TUNE
    model = OutfitScorer(visual, **cfg["scorer"])
    missing, unexpected = model.load_state_dict(torch.load(f"{path}/scorer.pt", map_location="cpu"), strict=False)
    assert not unexpected and all(k.startswith("visual.") for k in missing), (missing, unexpected)
    return model.to(device).eval(), preprocess, cfg


@torch.no_grad()
def embed_images(model, preprocess, pil_images, device=None):
    """Vecteurs CLIP (fine-tune) de nouvelles photos, ex : l'accessoire que l'utilisateur ajoute."""
    device = device or next(model.parameters()).device
    ims = []
    for im in pil_images:
        im = im.convert("RGB").copy(); im.thumbnail((448, 448)); ims.append(preprocess(im))   # comme a l'entrainement
    model.eval()
    return model.encode_images(torch.stack(ims).to(device).float())
