# Model card — FASHN VTON v1.5 as used in DressMe BO7 (pretrained, NOT trained by DressMe)

| | |
|---|---|
| Model | FASHN VTON v1.5 — maskless virtual try-on, pixel space (FASHN AI). Weights `fashn-ai/fashn-vton-1.5` |
| Support models | DWPose + YOLOX ONNX (`fashn-ai/DWPose`), human parser SegFormer-B4 (`fashn-ai/fashn-human-parser`) |
| DressMe changes | **None.** No fine-tuning, no LoRA, no weight edits. Exact hashes in `weights_manifest.json` |
| Task | person photo + garment photo + category → image of the person wearing the garment |
| Frozen config | 20 steps (preview default), 30 steps (alternative), guidance 1.5, seed 42, `segmentation_free=True`, 1 sample, garment_photo_type per garment (`model` in all experiments) |
| Output | 1 image, 576×768 (as measured) |

## Measured performance (all on ONE Kaggle Tesla T4, float32 fallback because T4 has no native bf16)
| Measurement | Value | Source / strength |
|---|---|---|
| Latency, 30 steps | ~423 s / image | measured in Phase 3 (18 runs); per-run times not re-logged in Phase 3b |
| Latency, 20 steps | 282.1, 282.8, 282.8, 283.4 s | Phase 4A, 4 runs, ≈ 1.5× faster than 30 steps |
| Peak VRAM | 11.16 GB (`torch.cuda.max_memory_allocated`, same at 20 and 30 steps) | torch allocator only; ONNX/CUDA context not included |
| Determinism | same inputs + same seed → bit-identical output (A1 == A2) | Phase 3 |
| 20 vs 30 steps quality | visually indistinguishable on 4 comparisons; mean abs pixel diff 0.34–0.45 / 255 | **1 person, 3 garments, downscaled images, no zoomed inspection** |
| Other GPUs / bf16 | **NOT MEASURED** | — |

## Quality evidence (what we actually know)
Visual inspection only. 1 person, 1 night photo, 6 Myntra garments (3 tops/bottoms compared in detail). No quantitative metric (no FID/LPIPS/garment-fidelity score), no human study, no second person, no daylight photo.
Observed failure modes on the **original** photo at seed 42: leftover original clothing on one leg (trousers 41161), a shoulder bag turned into a cream flap (tee 3128), colour drift (trousers grey-green at seed 7). A tighter person framing (tight 3:4 crop or padded canonical) looked cleaner at seed 42 but this was **seed-dependent**; tight crop is a *candidate*, the **original photo remains the default**.

## Intended use
Research/prototype virtual try-on inside DressMe with clearly framed single full-body photos and single-garment images (BO6 categories mapped to tops / bottoms / one-pieces).

## Out of scope / not evaluated
Fit or size prediction · body measurement · multi-person or partial-body photos (AvatarProfile suitability gates them) · layered outfits · children's images · fairness across skin tones, body shapes, or garment types (**not evaluated**) · adversarial/safety testing (**not evaluated**) · any commercial use (see `LICENSES_AND_AUDIT.md`: the human parser is non-commercial).

## Limitations & risks
Hallucinated garment details, leftover original clothing, colour drift, accessory artifacts, seed sensitivity; generated images of real people → require consent, retention limits, and a "generated image" disclosure in the product (not implemented). ~283 s/job on a T4 is far too slow for synchronous use.
