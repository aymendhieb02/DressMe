#!/usr/bin/env python3
"""Restore the inference package on a clean worker.

  python tools/restore.py --target /work/fashn --offline-weights fashn_weights_offline.zip     # private offline bundle
  python tools/restore.py --target /work/fashn --online                                       # re-download pinned revisions from HF

Steps: (1) pip install vendored FASHN source + pinned human-parser package, (2) place weights, (3) verify SHA-256.
torch/torchvision are NOT reinstalled (must match the worker's CUDA); see requirements.lock.txt for the tested versions."""
import argparse, json, subprocess, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from fashn_infer import verify_weights  # noqa: E402


def sh(cmd):
    print("+", " ".join(map(str, cmd)), flush=True); subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True); ap.add_argument("--offline-weights"); ap.add_argument("--online", action="store_true")
    ap.add_argument("--skip-install", action="store_true"); ap.add_argument("--onnxruntime", default="onnxruntime-gpu")
    a = ap.parse_args()
    if bool(a.offline_weights) == bool(a.online):
        ap.error("choose exactly one of --offline-weights ZIP or --online")
    weights = Path(a.target) / "weights"; weights.mkdir(parents=True, exist_ok=True)
    manifest_path = HERE / "weights_manifest.json"
    manifest = json.loads(manifest_path.read_text())

    if not a.skip_install:
        src = HERE / "vendor" / "fashn-vton-1.5"
        sh([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "-e", str(src)])
        deps = ["safetensors", "huggingface_hub", "pillow", "numpy", "opencv-python-headless", "tqdm", "einops", "matplotlib", "transformers", a.onnxruntime,
                "fashn-human-parser==0.1.1"]
        sh([sys.executable, "-m", "pip", "install", "-q", *deps])

    if a.offline_weights:
        with zipfile.ZipFile(a.offline_weights) as z:
            z.extractall(weights)
    else:
        from huggingface_hub import hf_hub_download, snapshot_download
        for rel, src in manifest["sources"].items():
            if rel.endswith("/*"):
                continue
            hf_hub_download(src["hf_repo"], Path(rel).name, revision=src["revision"], local_dir=str(weights / Path(rel).parent))
        hp = manifest["sources"]["human_parser/*"]
        snapshot_download(hp["hf_repo"], revision=hp["revision"], local_dir=str(weights / "human_parser"))

    v = verify_weights(weights, manifest_path)
    print(json.dumps(v, indent=2))
    sys.exit(0 if v["ok"] else 3)


if __name__ == "__main__":
    main()
