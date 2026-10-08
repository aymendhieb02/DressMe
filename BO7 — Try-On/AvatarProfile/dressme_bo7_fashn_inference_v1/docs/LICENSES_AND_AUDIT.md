# Licences and third-party dependency audit  (engineering notes — NOT legal advice)

Legend: **READ** = licence text read by us · **README** = stated in an upstream README only · **NOT VERIFIED** = could not be checked in this audit.

## ⚠ Blocker for commercial use
`fashn-human-parser` (loaded unconditionally by `TryOnPipeline`) inherits the **NVIDIA Source Code License for SegFormer**. We **READ** the text (copy in `licenses/`): §3.3 *"The Work and any derivative works thereof only may be used or intended for use non-commercially … 'non-commercially' means for research or evaluation purposes only."* → **The packaged pipeline is usable for research/evaluation (e.g. the Esprit project demo) but NOT for a commercial product** unless FASHN/NVIDIA grants other terms or the parser is replaced. This is a product/legal decision, not an engineering one; do not ship commercially before resolving it. Redistribution of the parser weights requires including the full licence text (§3.1) — it is included.

## Components
| Component | Used as | Licence | Status |
|---|---|---|---|
| FASHN VTON v1.5 source (`fashn-AI/fashn-vton-1.5`, vendored) | inference code | Apache-2.0 | **READ** (`licenses/FASHN-VTON-1.5-Apache-2.0.txt`) |
| `model.safetensors` (HF `fashn-ai/fashn-vton-1.5`) | try-on weights | repo README says Apache-2.0 | **README only — HF model-card licence NOT VERIFIED** (HF was unreachable from the audit sandbox) |
| DWPose ONNX + YOLOX (HF `fashn-ai/DWPose`) | pose detection | README: DWPose Apache-2.0, YOLOX Apache-2.0 | **README only**; HF repo licence NOT VERIFIED. Training-data terms (COCO-WholeBody etc.) NOT VERIFIED |
| `fashn-human-parser==0.1.1` (PyPI wheel sha256 `3d84a195…c04b8`) + HF weights `fashn-ai/fashn-human-parser` | person parsing | NVIDIA Source Code License for SegFormer (**non-commercial**) | **READ** |
| torch / torchvision | runtime | BSD-3-Clause | general knowledge, NOT VERIFIED per release |
| onnxruntime-gpu | pose ONNX runtime | MIT; needs NVIDIA CUDA/cuDNN runtime libs (NVIDIA EULA) | general knowledge, NOT VERIFIED |
| transformers, safetensors, huggingface_hub | loaders | Apache-2.0 | general knowledge, NOT VERIFIED |
| numpy, Pillow, opencv-python(-headless), einops, tqdm, matplotlib | utils | BSD / HPND / Apache-2.0 (+ bundled LGPL FFmpeg in opencv wheels) / MIT / MPL-2.0 / PSF-like | general knowledge, NOT VERIFIED |
| FastAPI, pydantic, uvicorn, python-multipart | API | MIT / MIT / BSD-3 / Apache-2.0 | general knowledge, NOT VERIFIED |

## Data and artefacts
* Myntra "Fashion Product Images" (Kaggle) garments were used for experiments only; **not included in any bundle**; redistribution terms NOT VERIFIED — do not ship them.
* No private photos are in the bundle. The smoke test uses the two public sample images from the FASHN repo (`examples/data`).
* The offline-weights zip contains third-party weights → **private/internal use only**, never publish it (public Kaggle dataset, GitHub release, etc.).
* Not packaged on purpose: optimizer states, extra checkpoints, full HF cache, notebooks' outputs.

## Related (not in the bundle, deferred 3D track)
SMPLer-X (S-Lab 1.0, non-commercial), SMPL-X (research/non-commercial), CatVTON (CC BY-NC-SA 4.0). They stay out of the product path.
