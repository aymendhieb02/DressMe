"""Software checks of the exported bundle. Run in a fresh process: python selftest.py [reference.npz]
They establish that the code behaves as specified - not that predictions are accurate on real photos."""
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from attributes import GarmentDescriber      # noqa: E402
from inference import GarmentClassifier      # noqa: E402

checks = []
def check(name, ok, detail=""):
    checks.append({"check": name, "passed": bool(ok), "detail": str(detail)})

d = GarmentDescriber()
clf = d.clf
ref = np.load(HERE / "parity_reference.npz")
imgs = [Image.fromarray(ref["img%d" % i]) for i in range(int(ref["n"]))]

check("eval mode, no gradients", not any(m.training for m in clf.model.modules()) and isinstance(clf.logits(imgs[:1]), np.ndarray))
lg = clf.logits(imgs)
check("classifier logit parity (synthetic images)", np.abs(lg - ref["logits"]).max() <= 1e-4, "max diff %.2e" % np.abs(lg - ref["logits"]).max())
for attr in d.heads:
    got = np.stack([d.probabilities(im)[attr] for im in imgs])
    check("attribute probability parity: %s (synthetic)" % attr, np.abs(got - ref["prob_" + attr]).max() <= 1e-4,
          "max diff %.2e" % np.abs(got - ref["prob_" + attr]).max())

outs = [d.predict(im) for im in imgs]
ok_elig = True
for o in outs:
    cat = o["description_fields"]["category"]
    for attr, info in o["attributes"].items():
        applies = cat in d.heads[attr]["classes"]
        ok_elig &= info["eligible"] == applies
        if not applies:
            ok_elig &= info["suggestions"] == [] and info["value"] == "unknown" and bool(info["reason"])
check("ineligible attributes: no value, no suggestions, reason given", ok_elig)
check("model predictions are never marked user_confirmed",
      all("user_confirmed" not in o["description_provenance"].values() for o in outs))
check("colour is never stated without user confirmation", all(o["description_fields"]["color"] == "unknown" for o in outs))
check("scores are labelled uncalibrated", all(o["score_type"] == "uncalibrated_softmax" for o in outs))

saved = clf.policy["review_threshold"]
clf.policy["review_threshold"] = 1.01                       # force the low-score path
low = d.predict(imgs[0])
clf.policy["review_threshold"] = saved
check("low category score: garment type withheld, no attributes asserted",
      low["description"] == "A garment." and low["description_provenance"]["category"] == "withheld_low_score"
      and not any(i["eligible"] for i in low["attributes"].values()) and low["needs_user_review"], low["description"])

c0 = clf.classes[0]
colour = clf.description.ALLOWED["color"][0]
usr = d.predict(imgs[0], confirmed={"category": c0, "color": colour, "sleeve_length": "long"})
check("user overrides win and are marked user_confirmed",
      usr["description_fields"]["category"] == c0 and usr["description_fields"]["color"] == colour
      and usr["description_fields"]["sleeve_length"] == "long" and colour in usr["description"]
      and all(usr["description_provenance"][k] == "user_confirmed" for k in ("category", "color", "sleeve_length")), usr["description"])
try:
    d.predict(imgs[0], confirmed={"color": "not-a-colour"})
    check("invalid user value is rejected", False)
except ValueError:
    check("invalid user value is rejected", True)
check("plural garments", all(clf.description.render({"category": c}) == "A pair of %s." % c
                             for c in clf.description.PLURAL if c in clf.classes))
check("unknown everything renders safely", clf.description.render({}) == "A garment.")

with tempfile.TemporaryDirectory() as tmp:
    bad = Path(tmp) / "broken.jpg"
    bad.write_bytes(b"this is not an image")
    buf = io.BytesIO(); imgs[0].save(buf, "JPEG"); cut = Path(tmp) / "truncated.jpg"; cut.write_bytes(buf.getvalue()[:200])
    for name, p in (("corrupt file", bad), ("truncated file", cut)):
        try:
            d.predict(str(p)); check("%s raises ValueError" % name, False)
        except ValueError as e:
            check("%s raises ValueError" % name, True, e)

base = GarmentClassifier().predict(imgs[0])
check("category-only fallback interface works", base["category"] == outs[0]["category"] and "attributes" not in base
      and base["description_fields"]["pattern"] == "unknown")

if len(sys.argv) > 1:                                       # real validation images supplied by the notebook
    ext = np.load(sys.argv[1], allow_pickle=False)
    paths = [str(p) for p in ext["paths"]]
    lg2 = clf.logits(paths)
    check("classifier logit parity (%d validation images)" % len(paths), np.abs(lg2 - ext["logits"]).max() <= 1e-4,
          "max diff %.2e" % np.abs(lg2 - ext["logits"]).max())
    res = [d.predict(p) for p in paths]
    for attr in d.heads:
        got = np.stack([d.probabilities(p)[attr] for p in paths])
        check("attribute probability parity: %s (validation images)" % attr, np.abs(got - ext["prob_" + attr]).max() <= 1e-3,
              "max diff %.2e" % np.abs(got - ext["prob_" + attr]).max())
    expected = json.loads(str(ext["expected_json"]))
    same = [r["description"] == e["text"] and r["description_fields"] == e["fields"] and r["description_provenance"] == e["provenance"]
            for r, e in zip(res, expected)]
    check("rendered text, fields and provenance parity (validation images)", all(same), "%d/%d identical" % (sum(same), len(same)))
    example_validation = {"image": Path(paths[0]).name, **res[0]}
else:
    example_validation = None

print(json.dumps({"passed": all(c["passed"] for c in checks), "n_checks": len(checks), "checks": checks,
                  "example": outs[0], "example_validation": example_validation}))
