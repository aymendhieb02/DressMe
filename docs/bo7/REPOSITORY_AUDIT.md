# Repository audit — Phase 0

Audit date: 2026-10-08. Scope: local checkout at `D:\5eme\DressMe\Projet_DressMe`.

## Git and remote

- The project directory was not a Git repository: `git rev-parse --show-toplevel`, `git status`, `git branch`, `git log`, and `git remote` all reported “not a git repository”. There is no local history, branch, origin, or dirty-worktree state to preserve.
- The configured HTTPS proxy points at `127.0.0.1:9`; `git ls-remote --heads https://github.com/aymendhieb02/DressMe.git` failed to connect to that proxy. The GitHub page fetch also failed in the available web cache. Remote emptiness, branch list, and repository metadata therefore remain **unverified**.
- `gh` is not installed. Git identity is configured as `aymendhieb02` / `aymen.dhieb@gmail.com`, but that does not establish GitHub authentication.
- No remote was changed and nothing was pushed. Creating or pushing `main`/`BO7` before checking remote branches could create an unrelated history or collide with existing work. Revisit Git initialization and branch publication after remote access is restored.

## Confirmed application components

| Area | Present and verified | Absent in this checkout |
|---|---|---|
| BO6 inference | `ml-service/app/` FastAPI service; `/health`, `/analyze`, `/describe`; Pillow format/content checks; structured errors; bundle checksum verification; one CPU `GarmentDescriber` loaded at startup; lock serializes predictions | User-facing review flow, application API, garment persistence, account ownership |
| BO6 model | `ml-service/bundle/` contains classifier and attribute code/configuration, taxonomy, deterministic description, quality checks and weights; bundle is checked by `checksums.json` | Evaluation on real phone photos; calibrated scores or human-verified taxonomy |
| BO6 tests | Five pytest files cover analyze, health, describe, concurrency, startup/checksum behavior | No frontend or application integration tests |
| BO6 source material | Reports, notebook, result/model archives under `BO6 — Smart Wardrobe Digitization/` | These materials are not the deployed service and are excluded from Git by the Phase 0 ignore rules |
| BO7 research | Several VTON archives and reports under `BO7 — Try-On/`; archived FASHN standalone source bundle includes a model card, licence notes, smoke-test tooling and settings | BO7 application API, job queue, worker integrated into DressMe, persistent jobs/results, UI |
| Frontend | None found; no React, TypeScript, Vite, or package manifest | Entire shared frontend |
| Shared backend/auth | None found; no FastAPI application backend, user/session code, or application APIs | Shared authentication and orchestration |
| Database | No PostgreSQL configuration, SQLAlchemy models, or Alembic migrations found | Shared persistence |
| Storage | No shared private storage abstraction found | Owner-checked uploads and private file serving |
| Infrastructure | Root `docker-compose.yml` has only `ml-service`, published at configurable host port 8001; service Dockerfile uses Python 3.11 and runs one Uvicorn worker | Frontend/backend/PostgreSQL/queue/worker stack; internal-only ML topology |

## BO6 interface details to preserve

- `/health` returns `status`, `model_version`, `taxonomy_version`, `description_version`, and `quality_version`.
- `/analyze` accepts multipart `image`, JPEG/PNG/WEBP, up to 10 MiB, and returns `{quality, prediction}`. Quality is advisory; prediction scores are explicitly uncalibrated softmax values and require user review.
- `/describe` accepts `{confirmed: {category, color, pattern, sleeve_length}}`, rejects extra fields and unsupported values, and returns deterministic description text, fields, provenance and schema version.
- Taxonomy version is `dressme-v0.2`; its 11 categories are `dress`, `jacket`, `jeans`, `shirt`, `shorts`, `skirt`, `sweater`, `sweatshirt`, `t-shirt`, `top`, `trousers`. `other` is not accepted by the ML `/describe` schema.
- The wrapper verifies model checksums at startup, creates one CPU model instance, and locks inference calls. The bundle directory is out of scope for modification.

## BO7 package evidence and risks

- `BO7 — Try-On/AvatarProfile/dressme_bo7_fashn_inference_v1 (1).zip` contains a standalone FASHN v1.5 inference package; it is an archive, not an integrated service. Its private offline weights archive is present separately and must not be committed or redistributed.
- The package README and config specify 20/30 steps, guidance 1.5, seed 42, segmentation-free true, one sample, and the three FASHN categories. This conflicts with the task's 15-step requirement.
- The package status ledger marks manifest generation, offline weights hash round-trip, clean GPU restoration/inference, and CUDA ONNX provider verification unverified. Its model card reports limited single-person research observations; these do not establish product quality or general performance.
- The archive's own licence note records a non-commercial human-parser restriction and incomplete verification of other model/runtime terms. Treat deployment as academic/non-commercial pending resolution.
- Hybrid Avatar V1.4 is described by the task as unvalidated on real user photos. Automatic initialization, manual editing, persistence, and product integration remain unproven and are a later feasibility milestone.

## Security and repository hygiene

The original `.gitignore` only excluded `.env`, Python caches, virtual environments, and coverage. Phase 0 expands it to ignore local secrets, private/generated images and data, research archives, notebooks, model weights, and cache artifacts. Confirmed `.env.example` contains only `ML_PORT=8001`.

## Verification performed

- `git status --short --branch`, `git branch -avv`, `git log --oneline --decorate -12`, `git remote -v`, and `git rev-parse --show-toplevel`: no Git repository.
- `git ls-remote --heads https://github.com/aymendhieb02/DressMe.git`: failed because configured proxy was unreachable; no branch list obtained.
- `gh auth status` and `gh repo view ...`: unavailable because `gh` is not installed.
- `pytest -q` from `ml-service/`: **13 passed**, one Starlette/httpx deprecation warning.
- Python 3.11.9, pytest 9.0.2, Git 2.42.0, Docker 28.1.1 are available. No Docker build or Compose validation was run.
