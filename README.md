# DressMe

DressMe is an integrated fashion and wardrobe application. It brings together outfit scoring and suggestions, catalog search, a private garment record, Taste discovery, and prototype avatar/try-on workflows behind one sign-in. This README describes the checkout as inspected on **5 November 2026**; model availability depends on local assets and configuration.

The running application in this workspace is [http://localhost:8002/](http://localhost:8002/). The public page at `/` is the hand-written `static/landing/index.html`.

## Why the project is useful

- A person can review garment predictions before saving, then search, filter, edit and export a private wardrobe record.
- Outfit of the Day combines weather, occasion and a selected catalog wardrobe; The Verdict gives a score and possible swaps.
- Taste reactions are saved per signed-in account and can drive recommendations and a broad style profile.
- The app makes useful distinctions: catalog examples, user-owned garments, generated suggestions, mock try-on previews and real inference have different labels and requirements.
- Most core workflows are served from one local application. The BO6 garment model is isolated in a second local service, and private images and account data stay in local project storage by default.

These are product capabilities, not a claim that every ML suggestion is accurate or that every optional integration is currently ready.

## Application map

| Area | Feature | What it does | Current qualification |
| --- | --- | --- | --- |
| Public | Landing page | Introduces DressMe and links to sign-in. | Hand-written and tracked in Git at `static/landing/index.html`. |
| Account | Sign-in, registration, recovery | Account-scoped data, CSRF-protected writes, local captured recovery email by default. | SMTP delivery needs private configuration. |
| Style Engine | Outfit of the Day / Daily Edit | Uses weather, occasion and catalog items; can restrict picks to a saved catalog wardrobe. | External weather calls and the pretrained text encoder may be needed. |
| Style Engine | The Verdict / Rate My Look | Scores a 2–5-piece outfit and proposes improvements. A separate 3B model writes the stylist comment. | The 3B model loads on app startup on this GPU. |
| Style Engine | Complete My Outfit | Completes a partial look with the exported completion model. | Requires `data/completion/`. |
| Shopping | Where to Buy / Find Similar | Finds related catalog pieces from an uploaded image and can surface shop results. | External shopping results depend on configured services. |
| Shopping | Wardrobe Completion | Analyzes a saved catalog-item wardrobe and suggests gaps and outfits. | Distinct from the private BO6 garment record. |
| Taste | Taste Studio | Discover, like, dislike and save pieces; offers account-based “For you” results. | Uses a bundled catalog and automatic style estimates. |
| Taste | Style Profile | Estimates broad styles from up to 12 photos, likes, or a bundled sample. | Uses the CPU ONNX model in `data/style/`. |
| Taste | Bubble Breaker | Mixes familiar and less-explored styles after enough likes. | Requires at least three liked pieces. |
| Wardrobe Check | Redundancy Check | Examines similar or duplicate pieces and suggests an edit. | Donation-place lookup uses an external map service. |
| My Studio | My Wardrobe / Add Garment | Private garment upload, BO6 category/attribute suggestions, human review, edit, search, export. | BO6 is a separate local inference service. |
| My Studio | My Avatar | Creates an avatar in the Avaturn creator, or imports a GLB, and makes a 2D image of it for try-on. | Needs `AVATURN_URL` and WebGL in the browser. |
| My Studio | Virtual Try-On / History | Dresses your avatar or a saved photo in pieces from your wardrobe. Jobs wait in a queue; History shows the person, garment and result. | `VTON_MODE=mock` gives labelled previews. `VTON_MODE=real` runs FASHN on a remote server or a local runtime. |
| Conversation | Style Assistant | Dressing/preferences controls and an outfit chat pipeline using BO5, BO1 and retrieval. | **Chat is paused on this PC** (`DRESSME_PARSER_ENABLED=off`); the controls remain available. |

The original app calls some sections by different names in code and in the top menu. The top menu is the user-facing map above.

## How it is put together

```text
Browser /                 -> static/landing/index.html (hand-written public page)
Browser /login and /app   -> static/index.html + static/studio/ + static/taste.js
api.py                    -> original feature routers, BO1/BO5 assistant, Taste, BO3
                         -> mounted Studio API at /studio-api
Studio API                -> SQLite + private local storage + optional Redis/RQ
                         -> BO6 FastAPI inference service on a separate local port
```

Main entry points and folders:

| Path | Responsibility |
| --- | --- |
| `api.py` | Integrated FastAPI entry point, authentication boundary, route wiring and landing/static mounts. |
| `static/index.html`, `static/studio/`, `static/taste.js` | Signed-in application and its browser modules. |
| `landing/src/`, `landing/public/`, `landing/vite.config.js` | Newer React/Vite landing source; build target is `static/landing/`. |
| `ootd.py`, `scoring.py`, `completion.py`, `similar.py`, `wardrobe.py` | Original outfit, scoring, completion, search and catalog-wardrobe features. |
| `reco.py`, `style.py`, `bubble.py`, `engine.py` | Taste recommendation, style profile and exploration. |
| `redundancy.py`, `donate.py`, `static/bo3.html` | Wardrobe Check. |
| `dressme/`, `bo1/score/`, `bo5/parser_for_local/` | Style Assistant contracts, BO1 scoring export and BO5 parser adapter. |
| `app/`, `alembic/` | Studio API, accounts, private garments, avatar, try-on jobs and database migrations. |
| `bo6_service/` | Independent BO6 garment classification/description service and bundle metadata. |
| `data/` | Bundled catalogs, thumbnails, embeddings, scoring/completion exports and Taste assets. |
| `scripts/dev/` | Windows setup, model restoration, start, check and stop scripts. |

## Models and assets

| Component | Where it is used | Location / behavior |
| --- | --- | --- |
| BO1 OutfitScorer | The Verdict and assistant scoring | Exported weights and embeddings in `data/` and `bo1/score/`. Scores are model estimates, not human ratings. |
| Qwen2.5-3B-Instruct | The Verdict stylist's written explanation | Loaded at application startup when CUDA and `DRESSME_LLM` are enabled; templates cover loading/failure. This model occupied about 3.9 GB of the 4 GB GPU during the 5 November check. |
| Qwen3-1.7B + LoRA | Style Assistant's natural-language parser | Adapter under `bo5/parser_for_local/parser_adapter/`, pinned base under `.cache/`. It is **disabled locally** and does not load at startup or on chat requests. |
| BO6 EfficientNet-B0 | Garment category/attribute suggestions | Checksum-verified `.pt` bundle in `bo6_service/bundle/`; separate CPU service. User confirms predictions before save. |
| Completion MiniGPT | Complete My Outfit | `data/completion/`. |
| CLIP/SigLIP family | Daily Edit and visual search | Some pretrained weights may be downloaded on first use. |
| Taste style classifier | Style Profile | CPU ONNX export in `data/style/`; Taste catalog and embeddings in `data/reco/`. |
| FASHN VTON 1.5 | Optional real virtual try-on | Needs `VTON_MODE=real`, Redis, and either `VTON_REMOTE_URL` or `VTON_RUNTIME_DIR`. Each job picks local or remote by free memory; `VTON_BACKEND_FORCE` overrides that. A remote image took 282 seconds in testing. |

The team-provided catalog and image data include `data/catalog.json`, `data/emb_clip.npy`, `data/emb_ft.npy` and `data/img/`. The approved BO6 `.pt` weights, local `.env`, runtime caches, databases and private images are intentionally outside Git. Preserve them when updating the checkout. Do not place credentials in the README or commit `.env`.

## Run this checkout on Windows

Validated setup expects Git, **Python 3.11 64-bit**, PowerShell and Node.js **20.19+ or 22.12+**. The current checkout is at `D:\5eme\DressMe\integration_DressMe`.

For an already prepared checkout:

```powershell
cd D:\5eme\DressMe\integration_DressMe
.\scripts\dev\start.ps1 -AppPort 8002 -Bo6Port 18023
.\scripts\dev\check.ps1 -AppPort 8002 -Bo6Port 18023
```

Open [http://localhost:8002/](http://localhost:8002/). The BO6 service at `127.0.0.1:18023` is for the backend, not a separate user-facing site. To stop services started by this checkout:

```powershell
.\scripts\dev\stop.ps1
```

For a fresh clone, run these from the repository root after obtaining the approved team model/data artifacts:

```powershell
.\scripts\dev\setup.ps1 -Developer -IncludeBo6
.\scripts\dev\restore-model-bundle.ps1 -SourceBundlePath 'D:\path\to\approved\bundle'
& .\.venv-app\Scripts\python.exe -m alembic upgrade head
.\scripts\dev\start.ps1 -AppPort 8002 -Bo6Port 18023
.\scripts\dev\check.ps1 -AppPort 8002 -Bo6Port 18023
```

`setup.ps1` creates `.venv-app` and `.venv-bo6`, installs locked dependencies, creates `.env` only if absent, and leaves the hand-written `static/landing/index.html` in place, skipping the landing build with a warning. To rebuild from `landing/`, delete that file first. The BO6 restore script checks the supplied weights. Migrations are an explicit step; startup does not run them. For a different machine, use two free ports and update the corresponding local origins/BO6 URL configuration.

`start.ps1` starts the application, the BO6 service, and, when Redis is reachable, the try-on dispatcher and worker. It tries to start the local Redis container; Docker Desktop must be running for that. Run `check.ps1` to see which dependencies are ready; a blocked try-on queue does not mean the whole application is down.

## Local configuration and current limitations

- `.env` is local and ignored by Git. On this PC `DRESSME_PARSER_ENABLED=off`, so Style Assistant chat deliberately returns `chat_disabled`; dressing and preference controls are still present. The 1.7B parser was failing before it could occupy VRAM. Setting it back to `on` without changing GPU capacity will recreate the NF4 memory error.
- The Verdict's 3B stylist model is kept on. It loads at startup; the basic outfit score does not depend on its prose generation. `DRESSME_LLM=off` would use template explanations, but that is **not** the current choice.
- Try-on images are generated one at a time, and each user can have 6 waiting (`MAX_OUTSTANDING_JOBS`). A remote server sees the person and garment images, and the page says so in its consent text. Never interpret a mock result as a fitted image or size prediction.
- Password recovery writes `.eml` files to the private local capture directory by default. Configure SMTP privately to send real email.
- `landing/src/` is not used by the page at `/`. `landing/index.html` never loads it, so a Vite build outputs that file's old campaign page, not the React design.
- Optional weather, shopping, map, avatar provider and upstream pretrained-model calls need network access or credentials. The app has fallbacks and explicit errors in some paths, but these integrations were not all verified in this inspection.

Useful local checks:

```powershell
Invoke-RestMethod http://localhost:8002/studio-api/health/ready
Invoke-RestMethod http://localhost:8002/studio-api/health/try-on
Invoke-RestMethod http://127.0.0.1:18023/health
```

Service process records and logs are in `.runtime/` inside this project. A `401` from an `/api/` feature route without signing in is expected. The private database and images are under `var/` according to local `.env`; do not remove them during setup or pulls.

## Further project records

- [Landing page analysis](docs/LANDING_ANALYSIS.md)
- [Current BO1/BO5 account integration notes](docs/SESSION_GENDER_INTEGRATION.md)
- [BO6 integration and optional G2L notes](docs/BO6_CHANGES.md)
- [Historical integration verification](docs/INTEGRATION_VERIFICATION.md)
- [Older project state snapshot](docs/PROJECT_STATE.md) — dated 31 October 2026 and not a current feature-status report.
