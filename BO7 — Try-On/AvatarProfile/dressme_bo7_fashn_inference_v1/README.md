# dressme_bo7_fashn_inference_v1 — frozen FASHN VTON v1.5 inference package

**What this is:** the *pretrained* FASHN VTON v1.5 pipeline (nothing trained by DressMe) frozen as the BO7 inference baseline, with pinned source, pinned weights (SHA-256), a standalone entry point, and a restore + smoke-test procedure.
**Status of each claim is in `docs/STATUS.md` — read it before relying on anything here.**

## Frozen defaults (`config/inference_defaults.json`)
20 steps (preview, default) · 30 steps (alternative, `--preset balanced`) · guidance 1.5 · seed 42 · `segmentation_free=True` · 1 sample · garment_photo_type per garment · person input = original photo (tight 3:4 crop = experimental candidate only).

## Layout
```
fashn_infer.py              standalone entry: one-shot CLI and --serve (JSON-lines worker used by the API)
config/inference_defaults.json
weights_manifest.json       SHA-256 + sizes + upstream revisions (generated on Kaggle by tools/make_manifest.py)
environment.json, requirements.lock.txt   versions of the environment the weights were validated in
vendor/fashn-vton-1.5/      exact FASHN source used (copied from the Kaggle clone; commit in the manifest)
tools/make_manifest.py      run once where weights are known good
tools/restore.py            pip install + place weights (offline zip or online pinned revisions) + verify hashes
tools/smoke_test.py         hash check -> load -> ONE real 20-step inference -> smoke_test_evidence.json
docs/ MODEL_CARD.md  LICENSES_AND_AUDIT.md  STATUS.md      licenses/ (full licence texts)
tests/test_bundle.py        CPU-only unit tests of hashing/params
```
Weights are NOT in the code zip. Two ways to get them: **offline** `dressme_bo7_fashn_weights_offline_PRIVATE.zip` (private, ~2.3 GB; includes pinned human-parser copy) or **online** pinned revisions from Hugging Face.

## Restore on a clean GPU worker (CUDA + a matching torch/torchvision already installed)
```bash
unzip dressme_bo7_fashn_inference_v1.zip && cd dressme_bo7_fashn_inference_v1
python tools/restore.py --target /work/fashn --offline-weights /path/dressme_bo7_fashn_weights_offline_PRIVATE.zip   # or: --online
python tools/smoke_test.py --weights-dir /work/fashn/weights --out /work/fashn/smoke_test_evidence.json
```
Restoration counts as **verified only if `smoke_test_evidence.json` has `all_checks_passed: true`** from a real run on a clean worker.

## Run
```bash
python fashn_infer.py --weights-dir /work/fashn/weights --person person.jpg --garment garment.jpg --category tops \
       --preset preview --output-dir out --result-json out/result.json        # add --preset balanced for 30 steps, --seed N
```
Exit codes: 0 ok · 2 bad input / weights or manifest missing · 3 weight hash mismatch · 4 CUDA OOM · 5 inference error. The result JSON records timing, torch peak VRAM, device, dtype and the **actual ONNX execution providers** (`CUDAExecutionProvider` must appear for detector and pose — otherwise DWPose silently runs on CPU).

## Reproducibility notes
* Human parser: upstream loads `fashn-ai/fashn-human-parser` by name from the Hub **without a revision pin**. This package copies a pinned snapshot to `weights/human_parser/` and loads it locally (`HF_HUB_OFFLINE=1` by default).
* Fixed seed ⇒ identical output on the same hardware/software (observed). Cross-GPU/driver bit-identity is NOT claimed.
* On GPUs without bf16 (e.g. T4) weights run in float32: slower and more VRAM (measured 11.2 GB, ~283 s at 20 steps).
