# DressMe architecture and implementation roadmap

Last reviewed: 2026-10-08. The status report and execution report contain current evidence; this roadmap records the architecture boundary and remaining acceptance work.

## Architecture

```text
React + TypeScript + Vite
       │ same-origin routes
       ▼
FastAPI application ─────► PostgreSQL
       │                       durable business/job state
       ├── private image volume
       ├── internal HTTP ───► existing BO6 ML service
       └── transactional outbox ───► Redis/RQ dispatcher and worker
                                      current worker: labelled mock only
```

The browser talks only to the application API. The API owns authentication, authorization, wardrobe, consent, eligibility, job state and asset retrieval. The existing BO6 service remains separate and its bundle/source are unchanged. The application API does not import Torch/FASHN. PostgreSQL is authoritative for jobs; Redis is transport. Private image files are accessed only by the backend and worker.

Only browser-facing development ports are published by Compose: frontend `8080` and application API `8000`. PostgreSQL, Redis and BO6 inference have no host-published ports. Compose defines persistent PostgreSQL, Redis AOF and private-image volumes. Configuration validates; runtime startup has not been verified because the Docker Engine pipe is inaccessible.

## Implemented components

| Area | Current implementation |
|---|---|
| Frontend | `frontend/`: React/Vite auth, garment upload/review/edit/wardrobe, consented person photos, mock job submission/history/status/result/deletion, account deletion. |
| Application API | `backend/app/`: FastAPI auth, safe errors/request IDs, BO6 client, wardrobe, private storage, person photos, mock jobs and cleanup. |
| Database | SQLAlchemy models and additive Alembic revisions `0001`–`0006` for identity/sessions, wardrobe, refresh families, VTON review, cleanup outbox, photos and mock jobs. |
| Queue | Redis/RQ with JSON serialization, PostgreSQL outbox, separate dispatcher and worker containers. |
| BO6 | Existing `ml-service/` preserved. Backend client uses its existing internal HTTP contracts. |
| Real VTON | Not implemented; real mode returns 503. Candidate mappings are versioned and disabled pending visual/product validation. |
| Avatar | Not implemented; supported Hybrid Avatar V1.4 source/material has not been found. |

See [`docs/bo7/INTEGRATION_CONTRACTS.md`](docs/bo7/INTEGRATION_CONTRACTS.md) for the implemented API and privacy behavior, and [`docs/bo7/IMPLEMENTATION_STATUS.md`](docs/bo7/IMPLEMENTATION_STATUS.md) for milestone status.

## Data and security boundaries

- Accounts use Argon2id password hashes and server-side, opaque HttpOnly session cookies. Mutations require session-bound CSRF and allowlisted Origin checks. Secure cookies are enabled in production.
- Database records carry owner IDs, foreign keys and timestamps. The API applies ownership predicates to asset, garment, photo, job and result operations.
- Uploads are bounded by bytes and decoded pixels, content-checked, orientation-corrected and re-encoded. Opaque storage keys are never public URLs or client-selected paths.
- Garments keep original BO6 predictions separate from user-confirmed fields, correction metadata, description provenance, photo type, and versioned candidate VTON policy.
- Jobs keep idempotency hashes/fingerprints, input and settings snapshots, state, attempt token/history and private result key. The database outbox makes Redis publication recoverable. The current mock worker is explicitly not an inference runtime.
- Deletions revoke database access first and use durable cleanup intents to retry private file removal. API responses disclose when physical cleanup remains queued.

## Roadmap and acceptance gates

### M0 — inspect and baseline: VERIFIED (local scope)

BO6 contracts, source, model artifacts and candidate VTON mapping were inspected. BO6 local tests and Compose configuration validation pass. These are not integrated runtime evidence.

### M1/M2 — shared API and wardrobe: IMPLEMENTED—UNVERIFIED

Auth, migrations, private uploads, BO6 HTTP client, garment review/correction, CRUD, ownership, and cleanup are implemented. SQLite tests and offline PostgreSQL SQL generation pass. Still required: apply migrations to a disposable PostgreSQL service and run the integrated BO6 path with approved model artifacts.

### M3/M4 — mock worker and unified client: IMPLEMENTED—UNVERIFIED

Consent, private person photos, job idempotency/outbox/worker contracts, mock output and UI are implemented. Unit tests use a fake queue and call worker logic directly; frontend build and one component test pass. Still required: run Redis/RQ and Compose services, exercise delivery recovery and the full browser journey, including two-user isolation.

### M5 — Gate A application demonstrator: BLOCKED / NOT VERIFIED

Pass only after PostgreSQL, Redis/RQ, backend, frontend and approved BO6 service start together, survive restart/recovery, and complete a browser-level user journey. Docker Engine access currently fails at the named pipe, so Compose configuration validation alone does not pass this gate.

### M6 — Gate B real FASHN: BLOCKED

Implement an isolated runtime adapter only after the frozen FASHN source can satisfy the requested strict FP16 profile, CUDA pose processing and model/license requirements. Verify actual application submission, worker isolation and cancellation/timeout, generated result, runtime measurements and representative output review. No mock fallback is permitted for real mode.

### M7 — Gate C Hybrid Avatar: BLOCKED

Locate a supported V1.4 source, then validate automatic initialization from a private photo, neutral user correction, persistence/save-reload, privacy/deletion and a useful downstream DressMe flow. Do not infer measurements or claim avatar completion from a manual editor alone.

### M8 — final QA and handoff: IN PROGRESS

Record exact test/runtime scope, complete integration and security regression checks, preserve private artifacts, and map every mandatory gate to evidence. BO7 remains incomplete until Gate C passes. Deployment is a separate evidence item.

## Local development

Use the PowerShell setup and migration commands in [`README.md`](README.md). Startup requires Docker Engine and approved BO6 model checkpoints in their documented private locations. Keep database and image volumes intact during restart; ordinary `docker compose down` preserves them. The current API and worker behavior is the explicit mock preview only.
