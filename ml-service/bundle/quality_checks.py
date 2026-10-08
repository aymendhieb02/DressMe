"""BO6 image quality assistant: advisory warnings before a photo is classified.

    from quality_checks import check_image
    report = check_image("photo.jpg")      # path or PIL.Image -> measurements, warnings, suggested actions

Rule-based (no model). A clean report does not mean the prediction will be correct."""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "quality_config.json").read_text(encoding="utf-8"))


def _luminance(image, long_side):
    if isinstance(image, Image.Image):
        im = image
    else:
        with Image.open(image) as f:
            f.load()
            im = f.copy()
    im = ImageOps.exif_transpose(im).convert("RGB")
    size = im.size
    if max(size) > long_side:                       # only ever downscale
        s = long_side / max(size)
        im = im.resize((max(1, round(size[0] * s)), max(1, round(size[1] * s))), Image.BILINEAR)
    return np.asarray(im.convert("L"), dtype=np.float32), size


def measure(image):
    g, (w, h) = _luminance(image, CONFIG["analysis_long_side"])
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4.0 * g[1:-1, 1:-1]) if min(g.shape) > 2 else np.zeros((1, 1))
    return {"width": int(w), "height": int(h), "min_side": int(min(w, h)),
            "brightness_mean": round(float(g.mean()), 2), "brightness_p05": round(float(np.percentile(g, 5)), 2),
            "brightness_p95": round(float(np.percentile(g, 95)), 2), "contrast_std": round(float(g.std()), 2),
            "sharpness": round(float(lap.var()), 2)}


def check_image(image):
    try:
        m = measure(image)
    except (OSError, SyntaxError, ValueError) as e:
        return {"version": CONFIG["version"], "readable": False, "measurements": {}, "advisory_only": True,
                "warnings": [{"code": "unreadable", "message": "The file could not be read as an image (%s)." % type(e).__name__,
                              "action": "Upload a JPEG or PNG photo."}]}
    t, warnings = CONFIG["thresholds"], []
    def warn(code, message, action):
        warnings.append({"code": code, "message": message, "action": action})
    if m["min_side"] < t["min_side_px"]:
        warn("low_resolution", "The photo is small (%d x %d px)." % (m["width"], m["height"]), "Retake it closer or at a higher resolution.")
    if t["blur_sharpness_below"] is not None and m["sharpness"] < t["blur_sharpness_below"]:
        warn("blurry", "The photo looks blurry.", "Hold the phone steady, tap to focus, and retake.")
    if m["brightness_mean"] < t["dark_mean_below"] or m["brightness_p95"] < t["dark_p95_below"]:
        warn("too_dark", "The photo is very dark.", "Add light or move near a window, then retake.")
    if m["brightness_mean"] > t["bright_mean_above"] and m["brightness_p05"] > t["bright_p05_above"]:
        warn("too_bright", "The photo is washed out.", "Avoid direct light or flash, then retake.")
    if m["contrast_std"] < t["low_contrast_std_below"]:
        warn("low_contrast", "The garment is hard to distinguish from the background.", "Use a plain background that contrasts with the garment.")
    return {"version": CONFIG["version"], "readable": True, "measurements": m, "warnings": warnings,
            "advisory_only": True, "thresholds_status": CONFIG["status"]}


if __name__ == "__main__":
    print(json.dumps({p: check_image(p) for p in sys.argv[1:]}))
