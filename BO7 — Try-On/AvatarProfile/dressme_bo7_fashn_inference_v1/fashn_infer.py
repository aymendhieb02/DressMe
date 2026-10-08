#!/usr/bin/env python3
"""DressMe BO7 - standalone FASHN VTON v1.5 inference entry point.

Runs with no notebook/Kaggle variables.  Two modes:

  one-shot : python fashn_infer.py --weights-dir W --person P --garment G --category tops [--preset preview]
  serve    : python fashn_infer.py --weights-dir W --serve      (JSON-lines on stdin/stdout; model loaded once)

Exit codes (one-shot): 0 ok | 2 bad input/weights missing | 3 weight hash mismatch | 4 CUDA OOM | 5 inference error
Pretrained FASHN weights only - this script never trains or modifies weights.
"""
from __future__ import annotations
import argparse, functools, hashlib, json, os, platform, sys, time, traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config" / "inference_defaults.json").read_text())
EXIT_BAD_INPUT, EXIT_HASH, EXIT_OOM, EXIT_ERROR = 2, 3, 4, 5


class JobError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, exit_code: int = EXIT_ERROR):
        super().__init__(message); self.code, self.message, self.retryable, self.exit_code = code, message, retryable, exit_code


def sha256_file(path: Path, chunk=1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def verify_weights(weights_dir: Path, manifest_path: Path) -> dict:
    """Compare every file listed in the manifest (relative to weights_dir) with its SHA-256."""
    manifest = json.loads(manifest_path.read_text())
    results, ok = {}, True
    for rel, meta in manifest["files"].items():
        p = weights_dir / rel
        if not p.exists():
            results[rel] = "MISSING"; ok = False; continue
        got = sha256_file(p)
        results[rel] = "OK" if got == meta["sha256"] else f"MISMATCH(got {got[:12]}...)"
        ok &= results[rel] == "OK"
    return {"ok": ok, "files": results, "manifest": str(manifest_path)}


def onnx_providers(pipeline) -> dict:
    out = {}
    try:
        wb = pipeline.pose_model.pose_estimation
        out = {"detector": wb.session_det.get_providers(), "pose": wb.session_pose.get_providers()}
    except Exception as e:  # attribute layout changed upstream
        out = {"error": repr(e)}
    try:
        import onnxruntime as ort
        out["available"] = ort.get_available_providers()
    except Exception:
        pass
    return out


def env_info() -> dict:
    info = {"python": platform.python_version(), "platform": platform.platform()}
    for m in ("torch", "torchvision", "onnxruntime", "numpy", "PIL", "transformers", "safetensors", "huggingface_hub"):
        try:
            mod = __import__(m); info[m] = getattr(mod, "__version__", "?")
        except Exception as e:
            info[m] = f"unavailable: {e!r}"[:80]
    try:
        import torch
        info["cuda_available"] = torch.cuda.is_available()
        info["torch_cuda"] = torch.version.cuda
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
            info["gpu_total_mb"] = round(torch.cuda.get_device_properties(0).total_memory / 2**20)
            info["bf16_supported"] = bool(torch.cuda.is_bf16_supported())
    except Exception:
        pass
    return info


def load_pipeline(weights_dir: Path, device: str | None = None, offline: bool = True):
    """Load TryOnPipeline; the human parser is loaded from the pinned local copy when present."""
    if offline:
        os.environ.setdefault("HF_HUB_OFFLINE", "1"); os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import fashn_vton.pipeline as P
    hp_dir = weights_dir / CONFIG["human_parser"]["local_dir_in_weights"]
    hp_source = "hf-hub-by-name (UNPINNED)"
    if hp_dir.is_dir() and any(hp_dir.iterdir()):
        P.FashnHumanParser = functools.partial(P.FashnHumanParser, model_id=str(hp_dir))
        hp_source = f"local:{hp_dir}"
    t0 = time.perf_counter()
    pipe = P.TryOnPipeline(weights_dir=str(weights_dir), device=device)
    return pipe, {"load_seconds": round(time.perf_counter() - t0, 2), "human_parser_source": hp_source}


def resolve_params(spec: dict) -> dict:
    preset = spec.get("preset") or CONFIG["default_preset"]
    if preset not in CONFIG["presets"]:
        raise JobError("BAD_PRESET", f"unknown preset '{preset}'", exit_code=EXIT_BAD_INPUT)
    steps = spec.get("num_timesteps") or CONFIG["presets"][preset]["num_timesteps"]
    cat = spec.get("category")
    if cat not in CONFIG["categories"]:
        raise JobError("BAD_CATEGORY", f"category must be one of {CONFIG['categories']}", exit_code=EXIT_BAD_INPUT)
    ptype = spec.get("garment_photo_type") or CONFIG["garment_photo_type_default"]
    if ptype not in ("model", "flat-lay"):
        raise JobError("BAD_PHOTO_TYPE", "garment_photo_type must be 'model' or 'flat-lay'", exit_code=EXIT_BAD_INPUT)
    return dict(category=cat, garment_photo_type=ptype, num_timesteps=int(steps),
                num_samples=int(spec.get("num_samples") or CONFIG["num_samples"]),
                guidance_scale=float(spec.get("guidance_scale") if spec.get("guidance_scale") is not None else CONFIG["guidance_scale"]),
                seed=int(spec.get("seed") if spec.get("seed") is not None else CONFIG["seed"]),
                segmentation_free=bool(spec.get("segmentation_free", CONFIG["segmentation_free"])))


def run_job(pipe, spec: dict) -> dict:
    """spec: person_path, garment_path, output_dir, category, [preset|num_timesteps, seed, ...]. Returns result dict."""
    import torch
    from PIL import Image
    params = resolve_params(spec)
    for k in ("person_path", "garment_path"):
        if not Path(spec.get(k, "")).is_file():
            raise JobError("INPUT_NOT_FOUND", f"{k} not found: {spec.get(k)}", exit_code=EXIT_BAD_INPUT)
    out_dir = Path(spec["output_dir"]); out_dir.mkdir(parents=True, exist_ok=True)
    person = Image.open(spec["person_path"]).convert("RGB"); garment = Image.open(spec["garment_path"]).convert("RGB")
    cuda = torch.cuda.is_available() and pipe.device.type == "cuda"
    if cuda:
        torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    try:
        res = pipe(person_image=person, garment_image=garment, **params)
        if cuda:
            torch.cuda.synchronize()
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        raise JobError("GPU_OOM", str(e)[:300], retryable=True, exit_code=EXIT_OOM)
    except Exception as e:
        raise JobError("INFERENCE_ERROR", repr(e)[:400], exit_code=EXIT_ERROR)
    seconds = round(time.perf_counter() - t0, 2)
    outputs = []
    for i, im in enumerate(res.images):
        p = out_dir / f"output_{i:02d}.png"; im.save(p); outputs.append({"path": str(p), "width": im.width, "height": im.height})
    return {"status": "ok", "outputs": outputs, "params": params, "inference_seconds": seconds,
            "torch_peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if cuda else None,
            "device": str(pipe.device), "dtype": str(pipe.inference_dtype)}


def _common_start(args):
    weights = Path(args.weights_dir).resolve()
    manifest = Path(args.manifest) if args.manifest else HERE / "weights_manifest.json"
    verification = None
    if not args.skip_verify:
        if not manifest.exists():
            raise JobError("MANIFEST_MISSING", f"{manifest} not found (use --skip-verify only for development)", exit_code=EXIT_BAD_INPUT)
        verification = verify_weights(weights, manifest)
        if not verification["ok"]:
            raise JobError("WEIGHT_HASH_MISMATCH", json.dumps(verification["files"]), exit_code=EXIT_HASH)
    try:
        pipe, load_info = load_pipeline(weights, args.device, offline=not args.online)
    except FileNotFoundError as e:
        raise JobError("WEIGHTS_MISSING", str(e)[:400], exit_code=EXIT_BAD_INPUT)
    return pipe, {"weights_verification": verification, **load_info, "onnx_providers": onnx_providers(pipe), "env": env_info()}


def main_oneshot(args) -> int:
    t_total = time.perf_counter()
    try:
        pipe, startup = _common_start(args)
        spec = dict(person_path=args.person, garment_path=args.garment, output_dir=args.output_dir, category=args.category,
                    preset=args.preset, num_timesteps=args.num_timesteps, seed=args.seed, guidance_scale=args.guidance_scale,
                    num_samples=args.num_samples, garment_photo_type=args.garment_photo_type,
                    segmentation_free=not args.no_segmentation_free)
        result = run_job(pipe, spec)
        result.update(startup); result["total_seconds"] = round(time.perf_counter() - t_total, 2)
        code = 0
    except JobError as e:
        result = {"status": "error", "error": {"code": e.code, "message": e.message, "retryable": e.retryable}}; code = e.exit_code
    except Exception as e:
        result = {"status": "error", "error": {"code": "INTERNAL_ERROR", "message": repr(e)[:400], "retryable": False},
                  "traceback": traceback.format_exc()[-1500:]}; code = EXIT_ERROR
    if args.result_json:
        Path(args.result_json).parent.mkdir(parents=True, exist_ok=True); Path(args.result_json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2)[:4000], file=sys.stderr)
    return code


def main_serve(args) -> int:
    """JSON-lines protocol. stdout is reserved for protocol messages; everything else goes to stderr."""
    proto = os.fdopen(os.dup(1), "w", buffering=1); sys.stdout = sys.stderr
    def send(obj): proto.write(json.dumps(obj) + "\n"); proto.flush()
    try:
        pipe, startup = _common_start(args)
    except JobError as e:
        send({"type": "fatal", "error": {"code": e.code, "message": e.message, "retryable": False}}); return e.exit_code
    except Exception as e:
        send({"type": "fatal", "error": {"code": "STARTUP_FAILED", "message": repr(e)[:400], "retryable": False}}); return EXIT_ERROR
    send({"type": "ready", **startup})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            spec = json.loads(line)
        except json.JSONDecodeError:
            send({"type": "error", "job_id": None, "error": {"code": "BAD_JSON", "message": "invalid JSON line", "retryable": False}}); continue
        if spec.get("op") == "shutdown":
            break
        try:
            send({"type": "result", "job_id": spec.get("job_id"), **run_job(pipe, spec)})
        except JobError as e:
            send({"type": "error", "job_id": spec.get("job_id"), "error": {"code": e.code, "message": e.message, "retryable": e.retryable}})
        except Exception as e:
            send({"type": "error", "job_id": spec.get("job_id"), "error": {"code": "INTERNAL_ERROR", "message": repr(e)[:400], "retryable": False}})
    return 0


def parse():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights-dir", required=True)
    ap.add_argument("--manifest", help="default: ./weights_manifest.json")
    ap.add_argument("--skip-verify", action="store_true", help="skip SHA-256 verification (development only)")
    ap.add_argument("--online", action="store_true", help="allow HF hub access (default: offline)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--person"); ap.add_argument("--garment")
    ap.add_argument("--category", choices=CONFIG["categories"])
    ap.add_argument("--garment-photo-type", choices=["model", "flat-lay"])
    ap.add_argument("--preset", choices=list(CONFIG["presets"]), help="default: preview (20 steps)")
    ap.add_argument("--num-timesteps", type=int); ap.add_argument("--seed", type=int); ap.add_argument("--guidance-scale", type=float)
    ap.add_argument("--num-samples", type=int); ap.add_argument("--no-segmentation-free", action="store_true")
    ap.add_argument("--output-dir", default="outputs"); ap.add_argument("--result-json")
    a = ap.parse_args()
    if not a.serve and not (a.person and a.garment and a.category):
        ap.error("--person, --garment and --category are required unless --serve")
    return a


if __name__ == "__main__":
    args = parse()
    sys.exit(main_serve(args) if args.serve else main_oneshot(args))
