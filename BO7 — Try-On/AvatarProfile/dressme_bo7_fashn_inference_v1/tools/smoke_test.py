#!/usr/bin/env python3
"""Restoration smoke test: verify hashes -> load pipeline -> ONE real inference -> evidence JSON.
Runs fashn_infer.py as a separate process (proves it does not rely on any notebook variables).
  python tools/smoke_test.py --weights-dir /work/fashn/weights --out smoke_test_evidence.json [--preset preview]
Uses the public sample images shipped in vendor/fashn-vton-1.5/examples/data (no private photos)."""
import argparse, datetime as dt, json, os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights-dir", required=True); ap.add_argument("--out", default="smoke_test_evidence.json")
    ap.add_argument("--preset", default="preview"); ap.add_argument("--person"); ap.add_argument("--garment"); ap.add_argument("--category", default="tops")
    a = ap.parse_args()
    a.weights_dir = str(Path(a.weights_dir).resolve()); a.out = str(Path(a.out).resolve())     # subprocess runs with cwd=/
    data = HERE / "vendor" / "fashn-vton-1.5" / "examples" / "data"
    person, garment = Path(a.person or data / "model.webp").resolve(), Path(a.garment or data / "garment.webp").resolve()
    work = Path(a.out).resolve().parent / "smoke_outputs"; work.mkdir(parents=True, exist_ok=True)
    res_json = work / "result.json"
    env = {k: v for k, v in os.environ.items() if k not in ("JPY_PARENT_PID", "KAGGLE_KERNEL_RUN_TYPE")}
    cmd = [sys.executable, str(HERE / "fashn_infer.py"), "--weights-dir", a.weights_dir, "--person", str(person), "--garment", str(garment),
           "--category", a.category, "--preset", a.preset, "--output-dir", str(work), "--result-json", str(res_json)]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd="/")          # cwd=/ : no accidental relative imports
    wall = round(time.perf_counter() - t0, 1)
    result = json.loads(res_json.read_text()) if res_json.exists() else {"status": "error", "error": {"message": "no result json"}}
    checks = {"process_exit_code_0": proc.returncode == 0, "status_ok": result.get("status") == "ok",
              "weights_hashes_ok": bool((result.get("weights_verification") or {}).get("ok")),
              "output_exists": bool(result.get("outputs")) and Path(result["outputs"][0]["path"]).stat().st_size > 10_000 if result.get("outputs") else False}
    prov = result.get("onnx_providers", {})
    on_cuda = result.get("device", "").startswith("cuda")
    checks["onnx_used_cuda_provider"] = result.get("status") == "ok" and ((not on_cuda) or ("CUDAExecutionProvider" in (prov.get("detector") or []) and "CUDAExecutionProvider" in (prov.get("pose") or [])))
    checks["ran_on_gpu"] = on_cuda
    checks["steps_were_20_or_preset"] = result.get("params", {}).get("num_timesteps") == (20 if a.preset == "preview" else 30)
    evidence = {"schema": "dressme.restoration_smoke_test/1", "run_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "wall_seconds_including_load": wall, "checks": checks, "all_checks_passed": all(checks.values()),
                "result": result, "stderr_tail": proc.stderr[-1500:],
                "note": "VERIFIED only if this file was produced by an actual run on a clean worker; all_checks_passed must be true."}
    Path(a.out).write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"all_checks_passed": evidence["all_checks_passed"], "checks": checks, "wall_seconds": wall,
                      "inference_seconds": result.get("inference_seconds"), "peak_vram_mb": result.get("torch_peak_vram_mb"), "providers": prov}, indent=2))
    sys.exit(0 if evidence["all_checks_passed"] else 1)


if __name__ == "__main__":
    main()
