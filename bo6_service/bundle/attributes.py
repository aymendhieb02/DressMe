"""BO6 full description interface: category + sleeve length + pattern, and colour suggestions.

    from attributes import GarmentDescriber
    result = GarmentDescriber().predict("photo.jpg")          # path or PIL.Image

Sleeve length and pattern come from small linear heads on the classifier's own features (trained on weak
catalog labels). Colour is only ever SUGGESTED: it enters the sentence after the user confirms it.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent


def colour_hist(canvas):
    """512-bin sqrt RGB histogram of the central region, near-white background removed."""
    h, w = canvas.shape[:2]
    c = canvas[int(h * .20):int(h * .80), int(w * .25):int(w * .75)].reshape(-1, 3)
    c = c[c.min(1) < 235]
    if len(c) == 0:
        return np.zeros(512, dtype=np.float32)
    q = (c >> 5).astype(np.int32)
    return np.sqrt(np.bincount(q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2], minlength=512) / len(c)).astype(np.float32)


class GarmentDescriber:
    def __init__(self, bundle=HERE, device="cpu"):
        bundle = Path(bundle)
        spec = importlib.util.spec_from_file_location("bo6_inference", bundle / "inference.py")
        inf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inf)
        self.clf = inf.GarmentClassifier(bundle=bundle, device=device)       # same weights, eval mode
        pack = torch.load(bundle / "attribute_heads.pt", map_location="cpu", weights_only=True)
        if pack["checkpoint_sha256"] != self.clf.arch["weights_sha256"]:
            raise ValueError("attribute_heads.pt was trained on a different classifier checkpoint")
        self.mu, self.sd = pack["mu"].numpy(), pack["sd"].numpy()
        self.heads = {a: {**h, "weight": h["weight"].numpy(), "bias": h["bias"].numpy()} for a, h in pack["heads"].items()}
        self._buf = {}
        last = [m for m in self.clf.model.modules() if isinstance(m, torch.nn.Linear)][-1]
        last.register_forward_hook(lambda mod, inp, out: self._buf.__setitem__("f", inp[0].detach().float().cpu().numpy()))

    def features(self, image):
        """[classifier embedding, colour histogram], standardised with the training statistics."""
        canvas = self.clf.canvas(image)
        with torch.no_grad():
            self.clf.model(self.clf._tensor(canvas)[None].to(self.clf.device))
        return (np.concatenate([self._buf["f"][0], colour_hist(np.asarray(canvas))]) - self.mu) / self.sd

    def probabilities(self, image):
        x, out = self.features(image), {}
        for attr, h in self.heads.items():
            z = h["weight"] @ x + h["bias"]
            p = np.exp(z - z.max())
            out[attr] = p / p.sum()
        return out

    def predict(self, image, confirmed=None):
        """confirmed: user-corrected fields; they override every prediction."""
        out, cat, source, confirmed = self.clf.classify(image, confirmed)
        probs, predicted, attrs = self.probabilities(image), {}, {}
        for attr, h in self.heads.items():
            info = {"eligible": cat in h["classes"], "reason": None, "threshold": h["threshold"],
                    "score_type": "uncalibrated_softmax", "suggestions": []}
            if not info["eligible"]:              # nothing is predicted or suggested for this garment type
                info["reason"] = "category withheld (low score)" if cat == "unknown" else "not applicable to '%s'" % cat
            else:
                p = probs[attr]
                order = np.argsort(-p)
                info["suggestions"] = [{"value": h["values"][int(i)], "score": float(p[i])} for i in order[:2]]
                if attr not in confirmed and h["threshold"] is not None and p[order[0]] >= h["threshold"]:
                    predicted[attr] = h["values"][int(order[0])]
            attrs[attr] = info
        d = self.clf.description.describe(cat, source, confirmed, predicted)
        for attr, info in attrs.items():
            info["value"], info["source"] = d["fields"][attr], d["provenance"][attr]
            info["stated_in_description"] = d["fields"][attr] not in ("unknown", "not_visible")
        out.update(description=d["text"], description_fields=d["fields"], description_provenance=d["provenance"],
                   description_version=d["schema_version"], attributes=attrs,
                   color_suggestions=attrs.get("color", {}).get("suggestions", []),
                   interface="GarmentDescriber (category + attributes)")
        return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python attributes.py <image> [<image> ...]")
    else:
        d = GarmentDescriber()
        print(json.dumps([d.predict(p) for p in sys.argv[1:]], indent=2 if len(sys.argv) == 2 else None))
