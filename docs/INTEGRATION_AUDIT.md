# Integration audit — 29 October 2026

## Source revisions and protection

- Team checkout: `aymendhieb02/DressMe`, `rihab` at `6db709ade062bad5c7ca7be7ee85d4b88c2fdfee`. Remote `integration_bo6_bo7` did not exist when fetched. New branch created from that exact revision.
- BO6/BO7 read-only source: `D:\5eme\DressMe\Projet_DressMe`, branch `feature/bo7-autonomous-mvp`, HEAD `0d921271142787419c113fed9b83670995332d91`. It had pre-existing modified and untracked BO7/frontend/report files; none was changed or committed by this integration.
- Target checkout: `D:\5eme\DressMe\projet_integration`. The original five public sections are Daily Edit, The Verdict, Finish the Look, Find Similar and Wardrobe Completion.
- Existing tracked file changes are limited to `.gitignore`, `.env.example`, `requirements.txt`, `api.py`, and `static/index.html`. See `PRESERVATION_MANIFEST.json` for every baseline blob hash and `INTEGRATION_VERIFICATION.md` for regression evidence.

| Changed original file | Integration purpose | Regression evidence |
|---|---|---|
| `.gitignore` | Exclude restored `.pt` weights, local database/storage and environments. | Staged file audit found no weights or private state. |
| `.env.example` | Add sanitized Studio service, storage and provider settings. | Live readiness and unconfigured provider route checked. |
| `requirements.txt` | Include copied backend dependencies without changing original package declarations. | Original API checks and copied backend suite passed. |
| `api.py` | Mount Studio API and expose only validated public Avaturn origin configuration. | Original root/catalog/examples/score and wardrobe routes, Studio readiness and origin rejection checked. |
| `static/index.html` | Add My Studio group, five sections, module/style and a section event after the original callback. | Five original sections, Studio deep link/Back, BO6 browser flow and unique IDs checked. |

## Architecture decision

Keep the team's FastAPI entrypoint and plain browser code. Mount the copied application API at `/studio-api`; the team API remains `/api/*`. Keep BO6 inference as a separate CPU process. Preserve the copied SQLAlchemy/Alembic/private storage/auth and Redis/RQ contracts. The new UI uses scoped CSS and a standalone vanilla JS module. The two applications share an HTTP origin but not catalog IDs, user data or database state. No global team login was added.

## Feature inventory and current state

| Area | Source → target | Status |
|---|---|---|
| Original team features | `api.py`, `similar.py`, `wardrobe.py`, `static/index.html` → same paths | Preserved; five sections navigated in browser; root/catalog/examples/score returned 200. Weather/CLIP/search external calls not fully exercised. |
| BO6 real classification and deterministic description | `ml-service/app`, `ml-service/bundle` → `bo6_service/` | Real service healthy with separately restored, checksum-verified weights. Browser and HTTP journey passed. |
| BO6 review, private wardrobe, search/sort/export | `backend/app/garments`, React UI → `app/garments`, vanilla studio UI | Main analyze/confirm/describe/save/edit/reload and private image verified. Search/export endpoints copied; full browser filter/export regression pending. |
| Auth/session/CSRF/ownership | `backend/app/auth` → `app/auth` | Copied; two-account HTTP check passed cross-user garment/image 404. Broader avatar/job isolation inherited but not newly exercised. |
| Private PostgreSQL/storage/migrations | `backend/app/models.py`, `storage`, `alembic` → same root packages | Dedicated database migrated through `0008_private_avatar_renders`. Source database untouched. |
| Avaturn avatar | `backend/app/avatars`, React provider integration → copied API, partial vanilla UI | Current avatar read/delete, GLB import, configured Avaturn SDK creator and private 3D viewer are ported. Actual provider initialization/export and PNG render capture/save are not verified or complete. |
| BO7 mock job queue | `backend/app/tryon` → `app/tryon` | API/worker contracts copied. Runtime is unavailable: no Redis broker/dispatcher/worker running. UI explicitly labels MOCK and gates submission. |
| BO7 real VTON | Notebook/research, no production worker adapter → no real adapter | Unavailable. No generated web result or GPU claim. FASHN/CatVTON research is not web inference. |
| Anywear/live camera | No useful verified target contract | Deferred, not integrated. |
| Backup BO6 ideas | Scope guide | Multi-garment detection/label OCR not implemented. Existing advisory photo checks and user review do not promote standalone backup modules. |

## Data and auth contract

Studio registration creates a separate private identity; all private routes derive owner from the server-side session. CSRF proof is obtained at login/register and bootstrapped for an existing session. Garment IDs are UUIDs and distinct from the team's numeric catalog indices. The original BO6 eligibility mapping remains a candidate mapping; it does not assert real VTON support. Private files are read through authenticated endpoints, never mounted under `/static`.

## Pre-publication audit

The baseline tracked `.env.example` contains blank `SERPAPI_KEY` and `IMGBB_KEY` placeholders. A filename scan of tracked history found no `.env`, private database, key or credential file; the model weights are ignored and absent from staging. This is a bounded filename check, not a full secret scan of every historical byte.
