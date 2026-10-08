#!/usr/bin/env python3
"""Run ONCE on the machine where the weights are known-good (the Kaggle session). Produces:
   weights_manifest.json (SHA-256 + sizes + upstream revisions), environment.json, requirements.lock.txt
Also copies the human-parser snapshot next to the other weights (weights/human_parser/) so it can be pinned and loaded offline."""
import argparse, datetime as dt, hashlib, json, os, platform, shutil, subprocess, sys
from pathlib import Path

FILES = ["model.safetensors", "dwpose/yolox_l.onnx", "dwpose/dw-ll_ucoco_384.onnx"]
HF = {"model.safetensors": "fashn-ai/fashn-vton-1.5", "dwpose/yolox_l.onnx": "fashn-ai/DWPose", "dwpose/dw-ll_ucoco_384.onnx": "fashn-ai/DWPose"}


def sha256(p, chunk=1 << 22):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120).stdout.strip()
    except Exception as e:
        return f"unavailable: {e!r}"


def hub_metadata(weights: Path, rel: str):
    """huggingface_hub (local_dir mode) stores '<commit>\\n<etag>' in .cache/huggingface/download/<rel>.metadata"""
    m = weights / ".cache" / "huggingface" / "download" / (rel + ".metadata")
    if m.exists():
        lines = m.read_text().splitlines()
        return {"revision": lines[0] if lines else None, "etag": lines[1] if len(lines) > 1 else None}
    return {"revision": None, "etag": None, "note": "no hub metadata found; revision unknown"}


def snapshot_human_parser(weights: Path):
    from huggingface_hub import snapshot_download
    src = Path(snapshot_download("fashn-ai/fashn-human-parser"))      # cached copy that the pipeline already used
    dst = weights / "human_parser"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False)                         # dereferences HF cache symlinks
    return src.name                                                    # snapshot folder name == commit hash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights-dir", required=True); ap.add_argument("--fashn-repo", required=True); ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    weights, out = Path(a.weights_dir), Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    hp_rev = snapshot_human_parser(weights)

    files, sources = {}, {}
    for rel in FILES:
        p = weights / rel
        if not p.exists():
            sys.exit(f"missing weight file: {p}")
        files[rel] = {"sha256": sha256(p), "size": p.stat().st_size}
        sources[rel] = {"hf_repo": HF[rel], **hub_metadata(weights, rel)}
    for p in sorted((weights / "human_parser").rglob("*")):
        if p.is_file():
            rel = "human_parser/" + p.relative_to(weights / "human_parser").as_posix()
            files[rel] = {"sha256": sha256(p), "size": p.stat().st_size}
    sources["human_parser/*"] = {"hf_repo": "fashn-ai/fashn-human-parser", "revision": hp_rev}

    repo = Path(a.fashn_repo)
    git = {"commit": run(["git", "rev-parse", "HEAD"], repo), "remote": run(["git", "remote", "get-url", "origin"], repo),
           "commit_date": run(["git", "log", "-1", "--format=%cI"], repo), "dirty": bool(run(["git", "status", "--porcelain"], repo))}
    manifest = {"schema": "dressme.weights_manifest/1", "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "weights_origin": "pretrained third-party weights (FASHN AI); NOT trained or fine-tuned by DressMe",
                "files": files, "sources": sources, "fashn_source": git,
                "human_parser_package": "fashn-human-parser==0.1.1 (PyPI wheel sha256 3d84a1959148d29f169ed78aa46b9ae8562e7df3f22465cc8f599adc8fdc04b8)"}
    (out / "weights_manifest.json").write_text(json.dumps(manifest, indent=2))

    freeze = run([sys.executable, "-m", "pip", "freeze"]).splitlines()
    keep = ("torch", "torchvision", "onnxruntime", "numpy", "pillow", "opencv", "safetensors", "huggingface", "transformers", "einops",
            "tqdm", "matplotlib", "fashn", "tokenizers", "scipy")
    lock = [l for l in freeze if l.lower().startswith(keep)]
    (out / "requirements.lock.txt").write_text("\n".join(lock) + "\n")
    env = {"python": platform.python_version(), "platform": platform.platform(), "nvidia_smi": run(["nvidia-smi"]).splitlines()[:15],
           "nvcc": run(["nvcc", "--version"]).splitlines()[-1:] or None, "pip_freeze_relevant": lock}
    try:
        import torch, onnxruntime as ort
        env.update(torch=torch.__version__, torch_cuda=torch.version.cuda, cudnn=torch.backends.cudnn.version(),
                   onnxruntime=ort.__version__, onnx_available_providers=ort.get_available_providers())
    except Exception as e:
        env["import_error"] = repr(e)
    (out / "environment.json").write_text(json.dumps(env, indent=2))
    print(json.dumps({"files": {k: v["size"] for k, v in files.items()}, "fashn_commit": git["commit"], "git_dirty": git["dirty"],
                      "model_revision": sources["model.safetensors"].get("revision"), "human_parser_revision": hp_rev}, indent=2))


if __name__ == "__main__":
    main()
