"""Pure-python checks of the bundle tooling (no torch/GPU needed): hashing, manifest verification, parameter rules."""
import hashlib, json, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fashn_infer as F


def make(tmp_path):
    w = tmp_path / "weights"; (w / "dwpose").mkdir(parents=True)
    (w / "model.safetensors").write_bytes(b"A" * 1000); (w / "dwpose" / "yolox_l.onnx").write_bytes(b"B" * 500)
    files = {r: {"sha256": hashlib.sha256((w / r).read_bytes()).hexdigest(), "size": (w / r).stat().st_size} for r in ("model.safetensors", "dwpose/yolox_l.onnx")}
    m = tmp_path / "m.json"; m.write_text(json.dumps({"files": files})); return w, m


def test_verify_ok_mismatch_missing(tmp_path):
    w, m = make(tmp_path)
    assert F.verify_weights(w, m)["ok"]
    (w / "model.safetensors").write_bytes(b"A" * 999 + b"X")
    r = F.verify_weights(w, m); assert not r["ok"] and r["files"]["model.safetensors"].startswith("MISMATCH")
    (w / "dwpose" / "yolox_l.onnx").unlink()
    assert F.verify_weights(w, m)["files"]["dwpose/yolox_l.onnx"] == "MISSING"


def test_frozen_defaults():
    p = F.resolve_params({"category": "tops"})
    assert (p["num_timesteps"], p["seed"], p["guidance_scale"], p["segmentation_free"], p["num_samples"], p["garment_photo_type"]) == (20, 42, 1.5, True, 1, "model")
    assert F.resolve_params({"category": "tops", "preset": "balanced"})["num_timesteps"] == 30
    assert F.CONFIG["person_input"]["default"] == "original"
    assert F.CONFIG["person_input"]["candidate"] == "tight_crop_3x4"


@pytest.mark.parametrize("bad", [{"category": "hat"}, {"category": "tops", "preset": "nope"}, {"category": "tops", "garment_photo_type": "x"}])
def test_bad_params(bad):
    with pytest.raises(F.JobError):
        F.resolve_params(bad)


def test_missing_manifest_refuses_to_start(tmp_path, capsys):
    import argparse
    a = argparse.Namespace(weights_dir=str(tmp_path), manifest=str(tmp_path / "none.json"), skip_verify=False, device=None, online=False)
    with pytest.raises(F.JobError) as e:
        F._common_start(a)
    assert e.value.code == "MANIFEST_MISSING"
