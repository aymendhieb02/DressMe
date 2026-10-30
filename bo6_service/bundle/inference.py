"""BO6 garment classifier (category-only interface). No notebook state, no network access, runs on CPU.

    from inference import GarmentClassifier
    result = GarmentClassifier().predict("photo.jpg")        # path or PIL.Image

For the full description (sleeve length, pattern, colour suggestions) use attributes.GarmentDescriber,
which wraps this class. This file alone is the documented fallback when attribute_heads.pt is absent.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image, ImageOps
from torchvision import models as tvm, transforms

HERE = Path(__file__).resolve().parent


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class GarmentClassifier:
    def __init__(self, bundle=HERE, device="cpu"):
        self.dir = Path(bundle)
        self.arch = _json(self.dir / "architecture.json")
        self.classes = _json(self.dir / "class_mapping.json")["classes"]     # index = model output index
        self.pre = _json(self.dir / "preprocessing.json")
        self.taxonomy = _json(self.dir / "taxonomy.json")
        self.policy = _json(self.dir / "review_policy.json")
        self.device = device
        if self.arch["num_classes"] != len(self.classes):
            raise ValueError("architecture.json and class_mapping.json disagree on the number of classes")
        m = tvm.get_model(self.arch["architecture"], weights=None)           # never downloads weights
        n = len(self.classes)
        if hasattr(m, "fc"):
            m.fc = nn.Linear(m.fc.in_features, n)
        elif isinstance(m.classifier, nn.Sequential):
            m.classifier[-1] = nn.Linear(m.classifier[-1].in_features, n)
        else:
            m.classifier = nn.Linear(m.classifier.in_features, n)
        state = torch.load(self.dir / "model_weights.pt", map_location="cpu", weights_only=True)
        m.load_state_dict(state["state_dict"], strict=True)
        self.model = m.to(device).eval()                                     # inference mode: no dropout, frozen BatchNorm
        s = self.pre["image_size"]
        self._resize = transforms.Resize((s, s), interpolation=transforms.InterpolationMode.BILINEAR, antialias=True)
        self._tensor = transforms.Compose([transforms.ToTensor(),
                                           transforms.Normalize(self.pre["mean"], self.pre["std"])])
        spec = importlib.util.spec_from_file_location("bo6_description", self.dir / "description.py")
        self.description = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.description)

    def rgb(self, image):
        """Path or PIL image -> upright RGB PIL image. Unreadable input raises ValueError."""
        try:
            if isinstance(image, Image.Image):
                im = image
            else:
                with Image.open(image) as f:
                    f.load()
                    im = f.copy()
            if self.pre["exif_transpose"]:
                im = ImageOps.exif_transpose(im)      # phone photos: honour the orientation tag
            return im.convert("RGB")
        except (OSError, SyntaxError, ValueError) as e:
            raise ValueError("unreadable image: %s" % type(e).__name__) from None

    def canvas(self, image):
        """Padded-to-square, resized RGB image: the exact pixels the model sees."""
        im = self.rgb(image)
        w, h = im.size
        if w != h:
            side = max(w, h)
            sq = Image.new("RGB", (side, side), tuple(self.pre["pad_fill"]))
            sq.paste(im, ((side - w) // 2, (side - h) // 2))
            im = sq
        return self._resize(im)

    def logits(self, images):
        x = torch.stack([self._tensor(self.canvas(i)) for i in images]).to(self.device)
        with torch.no_grad():
            return self.model(x).float().cpu().numpy()

    def classify(self, image, confirmed=None):
        """-> (result dict, category used for the description, its provenance, remaining confirmed fields)."""
        lg = self.logits([image])[0]
        pr = np.exp(lg - lg.max())
        pr = pr / pr.sum()
        order = np.argsort(-pr)
        score = float(pr[order[0]])
        thr = self.policy["review_threshold"]         # None = no validated threshold
        confident = thr is not None and score >= thr
        out = {
            "category": self.classes[int(order[0])],
            "score": score,                                   # raw softmax, NOT a calibrated probability
            "score_type": "uncalibrated_softmax",
            "suggestions": [{"category": self.classes[int(i)], "score": float(pr[i])} for i in order[:2]],
            "category_confident": bool(confident),
            "needs_user_review": bool(self.policy["always_review"] or not confident),
            "model_version": self.arch["experiment_id"],
            "taxonomy_version": self.taxonomy["version"],
        }
        confirmed = dict(confirmed or {})
        if "category" in confirmed:
            cat, source = str(confirmed.pop("category")).strip().lower(), "user_confirmed"
            if cat not in self.classes:
                raise ValueError("confirmed category is not a supported class: %r" % cat)
        elif confident:
            cat, source = out["category"], "classifier"
        elif thr is None:
            cat, source = out["category"], "classifier_no_validated_threshold"
        else:
            cat, source = "unknown", "withheld_low_score"     # low score: no garment type is asserted in the text
        return out, cat, source, confirmed

    def predict(self, image, confirmed=None):
        """Category-only description. confirmed: user-corrected fields, e.g. {"category": "shirt", "color": "blue"}."""
        out, cat, source, confirmed = self.classify(image, confirmed)
        d = self.description.describe(cat, source, confirmed)
        out.update(description=d["text"], description_fields=d["fields"], description_provenance=d["provenance"],
                   description_version=d["schema_version"], interface="GarmentClassifier (category only)")
        return out


if __name__ == "__main__":
    if len(sys.argv) == 2:
        print(json.dumps(GarmentClassifier().predict(sys.argv[1]), indent=2))
    else:
        print("usage: python inference.py <image>    (full description: python attributes.py <image>)")
