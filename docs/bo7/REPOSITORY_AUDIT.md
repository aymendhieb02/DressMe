# Repository audit — Phase 0

Audit date: 2026-10-08. Scope: `D:\5eme\DressMe\Projet_DressMe` and public GitHub repository `aymendhieb02/DressMe`.

## Git and publication state

- The initial checkout had no `.git` directory. A local repository was initialized with baseline commit `ea83c5d`; BO7 documentation commits `2cceb2d`, `b36d806`, and `fcea6b2` preserve the Phase 0 handoff, audit, contracts, and roadmap.
- Shared source commit `63d1904` is on local `main` and `feature/bo6-implementation`. It tracks BO6 service source/configuration and tests, plus BO6/BO7 reports, one BO6 notebook, two small BO7 inference ZIPs, and the extracted FASHN source package. The package contains source and licenses; private FASHN model weights are not tracked. These research artifacts were already present in the source commit and its public remote head.
- Local `BO7` preserves its documentation commits and includes non-fast-forward merge commits `36ab05c` and `b14d2b2`, integrating the shared baseline and subsequent `main` checksum fix. `main` does not contain BO7-specific documentation; BO7 is not merged into main.
- The remote is `https://github.com/aymendhieb02/DressMe.git`. A process-scoped no-proxy retry successfully reached GitHub. At the last read-only remote check before this publication attempt, refs were `main` and `feature/bo6-implementation`, both at `63d1904`; no remote `BO7` ref was observed. At that check, local `main` was `4c0ff9c` and local `BO7` was `b14d2b2`.
- Git-specific and general proxy variables were present in the process environment, all pointing to `127.0.0.1:9`; Git config itself had no HTTP proxy. Temporarily clearing the process proxy variables and using `git -c http.proxy= -c https.proxy= ...` worked. No global network settings were changed.
- GitHub CLI is unavailable. Git Credential Manager is configured as a credential helper, but its GitHub authentication status has not yet been established. An anonymous read of public refs does not establish push access.

## Application components now tracked on `main`

| Area | Verified state |
|---|---|
| BO6 inference | `ml-service/app/` FastAPI service; `GET /health`, `POST /analyze`, `POST /describe`; image validation; structured errors; checksum verification; one CPU `GarmentDescriber` loaded at startup; prediction calls serialized with a lock |
| BO6 model source | `ml-service/bundle/` includes classifier/attribute source, deterministic description and quality code, taxonomy/configuration, manifest, and a synthetic parity fixture. The two trained checkpoints are excluded from Git. |
| BO6 tests | Five pytest files cover analyze, health, describe, concurrency, and startup/checksum behavior. The service suite passes locally with the checkpoints present. |
| Infrastructure | Root Compose file contains only the BO6 ML service and publishes its diagnostic port on host port 8001. Dockerfile uses Python 3.11 and runs a single Uvicorn worker. |
| BO7 research source | `BO7 — Try-On/AvatarProfile/dressme_bo7_fashn_inference_v1/` contains standalone pretrained FASHN v1.5 source, upstream source/license notes, settings, and smoke-test tooling. It is not integrated into the DressMe application or a worker. |
| Shared app | No React/Vite frontend, shared application backend/auth, PostgreSQL, SQLAlchemy/Alembic, or private storage abstraction exists. |

The current BO6 taxonomy is `dressme-v0.2`: `dress`, `jacket`, `jeans`, `shirt`, `shorts`, `skirt`, `sweater`, `sweatshirt`, `t-shirt`, `top`, `trousers`. `/describe` rejects `other`. Scores are uncalibrated and user review is required.

## Required BO6 model artifacts

The tracked `ml-service/bundle/checksums.json` expects `model_weights.pt` and `attribute_heads.pt` at `ml-service/bundle/`. The actual files are ignored and excluded from Git. See `ml-service/ARTIFACTS.md` for approved private delivery and verification. Missing files or checksum/size mismatches fail bundle verification; Docker build's bundle self-test also fails without valid local artifacts. The exported bundle was not modified.

## BO7 behavior and unresolved risks

- Pretrained FASHN VTON v1.5 is the selected model. The target contract is float16, 15 steps, guidance 1.5, seed 42, segmentation-free, one sample. These settings have not been verified by a real GPU-backed smoke test.
- The included archived config specifies 20-step preview and 30-step balanced presets. This conflicts with the 15-step target. Do not treat the included source defaults as the approved app contract.
- The source package status says its weights manifest/export, clean GPU restoration/inference, and actual CUDA ONNX provider verification are not verified. FASHN/DWPose/human-parser licence and redistribution questions remain; a package licence note identifies a non-commercial human-parser dependency.
- Research CSV evidence maps some garment labels to `tops`, `bottoms`, and `one-pieces` but explicitly says “Candidate single garment; inspect images”. BO6-to-FASHN mappings remain candidates pending image-based validation. Jackets are not automatically eligible until compatibility is established.
- Hybrid Avatar V1.4 has not been validated on real user photos. Automatic initialization, manual editing, persistence, and product integration remain open feasibility questions.
- Current public `main` contains BO6/BO7 research PDFs and a BO6 notebook in addition to the application baseline. The BO7 report identifies its controlled cases as VITON-HD from a Kaggle mirror under CC BY-NC 4.0 and says the original person photo is not included in one exported comparison. The BO6 notebook visibly embeds catalogue/model images from the Kaggle fashion-product dataset; that dataset's redistribution terms were not verified in this audit. No private offline weights archive or BO6 checkpoint was found in the tracked tree. Preserve this provenance/license caveat in future publication decisions.

## Privacy and ignore rules

`.gitignore` covers credentials, environments, caches, datasets, local databases, personal/generated images, archives, notebooks, and model checkpoints. It keeps the synthetic `ml-service/bundle/parity_reference.npz` fixture. Ignore rules do not remove already tracked files. The two trained BO6 `.pt` files and the private offline FASHN weights archive are not in the current `main` tree.

## Verification performed

- `git ls-remote --heads origin` (with process-only proxy override): remote `main` and `feature/bo6-implementation` refs observed at `63d1904`; no `BO7` ref at that time.
- The committed bundle blobs match all tracked entries in `checksums.json`; root `.gitattributes` now pins LF for `ml-service/bundle/**` so Windows autocrlf settings cannot change the manifest bytes.
- `pytest -q` in `ml-service/`: 13 passed after restoring byte-exact bundle files; one Starlette/httpx deprecation warning.
- `docker compose config --quiet`: passed. No image build or real inference verification is claimed.
- Git Credential Manager is configured, but a no-prompt credential probe found no stored GitHub username/token. Push authentication remains unverified; GitHub CLI is unavailable.
- The architecture handoff document was absent from the checkout and inspected archives. `ARCHITECTURE_HANDOFF.md` remains explicitly provisional.
