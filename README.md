# DressMe

DressMe is a fashion and wardrobe application. It suggests outfits for the weather and occasion, scores looks, learns your taste, keeps a private record of your clothes, and shows your clothes on your own avatar with virtual try-on, all behind one sign-in.

**Version 1.0.0** · **To run it, see [RUN.md](RUN.md).**

## Features

| Menu | Feature | What it does | Needs |
| --- | --- | --- | --- |
| Public | Landing page | Introduces DressMe, with scroll animation and a mobile menu. | Nothing |
| Account | Sign-in, registration, recovery | Private accounts with CSRF-protected writes. | SMTP settings to send real email; otherwise recovery emails are saved locally |
| Style Me | Outfit of the Day | Builds a look from the weather and occasion, then can apply its catalog clothing pieces to your avatar. | Weather access; the text encoder may download on first use; Real try-on for the avatar preview |
| Style Me | Rate My Look | Scores a 2–5-piece outfit and proposes swaps. A 3B model writes the stylist comment. | Scoring exports; GPU for the comment |
| Style Me | Complete My Outfit | Completes a partial look. | `data/completion/` |
| Style Me | Style Assistant | Outfit chat using the BO5 parser, BO1 scoring and retrieval. | A GPU with enough memory; turn it off with `DRESSME_PARSER_ENABLED=off` |
| Shopping | Where to Buy | Finds similar catalog pieces from a photo, and shops when configured. | Shopping keys for shop results |
| Shopping | Wardrobe Completion | Finds the pieces that unlock the most new outfits. | A saved catalog wardrobe |
| Taste | Taste Studio | Discover, like, dislike and save pieces, with a For you selection. | Bundled catalog |
| Taste | Style Profile | Estimates four broad styles from up to 12 photos or your likes. | ONNX model in `data/style/` |
| Taste | Bubble Breaker | Mixes familiar and less-explored styles. | At least three likes |
| Wardrobe Check | Redundancy Check | Finds similar or duplicate pieces and suggests what to let go. | A saved wardrobe; a map service for donation places |
| My Studio | My Wardrobe, Add Garment | Upload a photo, review the suggestions, then search, edit and export your clothes. | BO6 service; manual add works without it |
| My Studio | My Avatar | Creates an avatar with Avaturn and makes a 2D image of it with the arms lowered. | `AVATURN_URL`, WebGL in the browser |
| My Studio | Virtual Try-On | Creates separate try-ons or applies up to four wardrobe garments in order, feeding each generated image into the next step. | Redis, plus FASHN for real results |
| My Studio | Try-On History | Shows the starting person, ordered garments and final result, including catalog outfits started from Outfit of the Day. | Redis |

Scores, predictions and try-on images are model estimates. They are not measurements, size advice or human ratings.

## How it fits together

```text
Browser /           → static/landing/index.html   (public page)
Browser /app        → static/index.html + static/studio/ + static/taste.js
api.py              → original features, BO1/BO5 assistant, Taste, BO3
                    → Studio API mounted at /studio-api
Studio API          → SQLite + private local storage
                    → BO6 service on its own port
                    → Redis → dispatcher → worker → FASHN (Kaggle or local)
```

| Path | Responsibility |
| --- | --- |
| `api.py` | Entry point, sign-in boundary, route wiring and page routes. |
| `app/` | Studio API: accounts, garments, avatars, try-on, storage. |
| `alembic/` | Database migrations, run explicitly. |
| `static/studio/`, `static/studio.js` | My Studio pages. |
| `static/landing/index.html` | Hand-written public page, tracked in Git. |
| `static/vendor/` | Avaturn SDK, model-viewer and `three.js`. |
| `bo6_service/` | Separate garment classification and description service. |
| `ootd.py`, `scoring.py`, `completion.py`, `similar.py`, `wardrobe.py` | Original outfit, scoring and search features. |
| `reco.py`, `style.py`, `bubble.py`, `engine.py` | Taste features. |
| `redundancy.py`, `donate.py`, `static/bo3.html` | Wardrobe Check. |
| `dressme/`, `bo1/`, `bo5/` | Style Assistant, BO1 scoring and the BO5 parser. |
| `wardrobe_owned.py` | Adds your own garments to Wardrobe Completion when `BO6_ENABLED=1`. |
| `data/` | Catalogs, thumbnails, embeddings and exported models (Git LFS). |
| `scripts/dev/` | Setup, start, check and stop scripts. |
| `landing/` | Unused React source. A build outputs the old campaign page, so `setup.ps1` skips it. |

## My Studio pipelines

### Add Garment and My Wardrobe (BO6)

```text
Photo → cleaned → BO6 suggests category and details → you review → description → saved
```

The app never saves a prediction without your review. `bo6_service/bundle/` holds the EfficientNet-B0 model, which runs on CPU. Starting with `start.ps1 -G2L` uses the CLIP-based `bundle_g2l/` instead. Descriptions are templates filled with your confirmed values.

Key files: `app/garments/router.py`, `app/ml/client.py`, `app/garments/eligibility.py`, `static/studio/wardrobe.js`, `bo6_service/app/main.py`.

### My Avatar (BO7)

```text
Consent → Avaturn creator → GLB saved → arms lowered with three.js → 2D PNG saved
```

The pose is applied in memory, so the saved GLB never changes. Images made with an older profile are replaced when the page opens.

Key files: `static/studio/avatar.js`, `static/studio/avatar-render.js`, `app/avatars/router.py`, `app/avatars/render_profile.py`.

### Virtual Try-On and the queue (BO7)

```text
Choose a person and clothes → separate jobs or one sequential outfit job
  → dispatcher → Redis → worker → FASHN on Kaggle or locally
  → final result saved with the starting image and garment order → Try-On History
```

The sequential option applies garments in the order selected. Each generated image becomes the person input for the next call, and history keeps the starting image, ordered garment photos and final output together. Earlier garments may shift during later steps. The worker makes one image at a time, and each user can have 6 jobs waiting. A real image takes about 5 minutes on Kaggle. If a worker stops mid-job, the dispatcher retries the job once.

Outfit of the Day has a **Try it on me** action for compatible clothing pieces in its displayed look. It skips shoes and accessories, runs the same sequence workflow, and shows the result beside the OOTD card on wide screens. The final image is saved in Try-On History with its catalog garments. A conservative edge-background remover makes the preview transparent when the output has a uniform background; it keeps the original image when it cannot separate the background safely.

For each job, the app uses the local runtime when `VTON_RUNTIME_DIR` is set and there is enough free memory, and the remote server otherwise. `VTON_BACKEND_FORCE` overrides that choice.

Key files: `static/studio/tryon.js`, `app/tryon/router.py`, `app/tryon/dispatcher.py`, `app/tryon/worker.py`, `app/tryon/worker_tasks.py`, `app/tryon/adapters.py`.

**For the best result,** use garment photos on a plain background. The model treats a busy background as part of the garment.

## Models

| Model | Used by | Location |
| --- | --- | --- |
| BO1 OutfitScorer | Rate My Look, Style Assistant | `data/`, `bo1/score/` |
| Qwen2.5-3B-Instruct | Stylist comment in Rate My Look | Loads at startup on CUDA unless `DRESSME_LLM=off`; templates are used otherwise |
| Qwen3-1.7B + LoRA | Style Assistant parser | `bo5/parser_for_local/parser_adapter/`, base model in `.cache/` |
| BO6 EfficientNet-B0 | Garment suggestions | `bo6_service/bundle/` |
| Completion MiniGPT | Complete My Outfit | `data/completion/` |
| CLIP / SigLIP family | Outfit of the Day, visual search | Some weights download on first use |
| Taste style classifier | Style Profile | `data/style/` (ONNX, CPU) |
| FASHN VTON 1.5, DWPose, human parser | Real try-on | Kaggle or a local runtime, outside Git |

BO6 weights, `.env`, databases and private images are not in Git. Keep them when updating.

## Configuration

Settings live in `.env`, created from `.env.example` and ignored by Git.

| Setting | Purpose |
| --- | --- |
| `VTON_MODE` | `mock` for labelled previews, `real` for FASHN |
| `VTON_REMOTE_URL`, `VTON_REMOTE_API_KEY` | Remote try-on server |
| `VTON_RUNTIME_DIR` | Local FASHN runtime |
| `VTON_BACKEND_FORCE` | Force `local` or `remote` |
| `MAX_OUTSTANDING_JOBS` | Waiting jobs per user |
| `AVATURN_URL`, `AVATURN_EXPORT_ORIGINS` | Avatar creator |
| `BO6_SERVICE_URL`, `BO6_ENABLED` | BO6 address, and garments in Wardrobe Completion |
| `DRESSME_PARSER_ENABLED`, `DRESSME_LLM` | Turn the Style Assistant parser or the 3B model off |
| `REDIS_URL` | Queue connection |
| `SMTP_*`, `EMAIL_DELIVERY_MODE` | Real recovery emails |
| `SERPAPI_KEY`, `IMGBB_KEY` | Shop results |

## Privacy

- Private images and accounts stay in local project storage by default.
- Each user can reach only their own garments, avatar, photos and try-on jobs.
- Real try-on on a remote server sends the person and garment images there, and the consent text says so.
- Using an avatar or photo for try-on needs explicit consent.
- Deleting an avatar also removes try-on history made from its saved avatar image.

## Tests

```powershell
$env:VTON_MODE = 'mock'
$env:FRONTEND_ORIGINS = 'http://localhost:8001,http://localhost:8002'
.\.venv-app\Scripts\python.exe -m pytest tests bo3/tests
```

Those two settings make the run independent of your `.env`. Version 1.0.0 gives 409 passed and 1 failed: `test_adapter_receipt_hash_is_real` needs `DRESSME_PARSER_ENABLED=on`.

## Known limits

- Coats, cardigans, blouses and jumpsuits are not available for try-on yet.
- OOTD try-on supports catalog tops, bottoms, outerwear and dresses; shoes and accessories are omitted from that sequence.
- Background removal only applies when the output has a uniform, edge-connected background.
- A Kaggle session can stop, and jobs then fail until it restarts.
- The Kaggle server takes one image at a time and refuses other requests while busy.
- Try-on quality depends on the garment photo and the pose.

## Licenses

FASHN, DWPose and the human parser are third-party models with their own terms. The bundled human parser is limited to non-commercial research and evaluation unless other terms are obtained. `three.js` is MIT, `model-viewer` is Apache-2.0, and the Avaturn SDK is MIT; see `static/vendor/`.

## More documents

- [Run commands](RUN.md)
- [BO6 integration notes](docs/BO6_CHANGES.md)
- [BO1 and BO5 local notes](docs/BO1_BO5_LOCAL.md)
- [Account and gender integration notes](docs/SESSION_GENDER_INTEGRATION.md)
- [Landing page analysis](docs/LANDING_ANALYSIS.md)
- [Integration verification](docs/INTEGRATION_VERIFICATION.md) (historical)
- [Project state snapshot](docs/PROJECT_STATE.md) (historical, October 2026)
