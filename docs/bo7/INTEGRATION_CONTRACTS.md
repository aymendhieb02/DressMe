# BO6 ↔ BO7 integration contracts

Last reviewed: 2026-10-08. This document distinguishes implemented local contracts from runtime or product acceptance that remains open.

## Shared application boundary

- The browser calls the application API. FastAPI owns accounts, wardrobe, private person photos, consent, jobs, results and private storage keys.
- BO6 inference remains the existing service at `/health`, `/analyze` (multipart `image`) and `/describe` (JSON `confirmed`). The application backend calls it over internal HTTP; the frontend does not call it directly.
- PostgreSQL is the intended source of business state. Redis/RQ transports asynchronous work. The API imports neither Torch nor FASHN.
- Compose publishes the development frontend and backend only. PostgreSQL, Redis and BO6 are internal services. Compose configuration passed validation; service startup has not been verified because Docker Engine access is denied.

## BO6 prediction and garment-review contract

- Keep taxonomy `dressme-v0.2`, prediction/quality snapshots, description provenance and `uncalibrated_softmax` score semantics. Scores are suggestions, not probabilities. Quality warnings are advisory; users review and confirm fields before saving.
- The application retains source prediction separately from user-confirmed category, attributes, photo type, description provenance and correction flags. The user may correct a garment and the versioned VTON decision is recomputed.
- Supported upload formats are JPEG, PNG and WEBP; server-side decoding, size and pixel limits, EXIF orientation and re-encoding are applied. Images and results use opaque private keys and authenticated owner-scoped retrieval.
- The versioned mapping is a candidate semantic map only:

| BO6 category | Candidate FASHN category | Real VTON status |
|---|---|---|
| `t-shirt`, `shirt`, `top`, `sweater`, `sweatshirt` | `tops` | Disabled; no visual/product validation |
| `jeans`, `trousers`, `shorts`, `skirt` | `bottoms` | Disabled; no visual/product validation |
| `dress` | `one-pieces` | Disabled; no visual/product validation |
| `jacket` | None | Unsupported pending evidence |
| Unknown or unmapped class | None | Unsupported |

Garments record `garment_photo_type` as user-confirmed `flat-lay` or `model`. A candidate category supports only the mock workflow contract; it does not mean real-inference eligibility. The mock preview performs no generation and does not estimate fit.

## Person-photo and job API (implemented mock contract)

Routes are owner-scoped and require explicit consent before photo upload:

- `POST /person-photos`, `GET /person-photos`, `GET /person-photos/{id}/image`, `DELETE /person-photos/{id}`.
- `POST /try-on/jobs` accepts a reviewed garment ID and person-photo ID, with an `Idempotency-Key`. `GET /try-on/jobs`, `GET /try-on/jobs/{id}`, and `GET /try-on/jobs/{id}/result` provide history/status/private result. `POST /try-on/jobs/{id}/cancel` requests cancellation; `DELETE /try-on/jobs/{id}` deletes the job and dependent result.
- Job states are `queued`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`. The mock output is a labelled contact sheet of the two inputs; it is not a generated outfit, fit estimate or body measurement.
- Mode is stored in each job. `VTON_MODE=real` currently rejects submission with `real_vton_unavailable`; it never substitutes a mock output. The worker currently routes only `run_mock_job`.
- Same owner/key/request returns the same job; reusing a key for different inputs returns 409. The database has an owner/key unique constraint. A transactional outbox covers the database/Redis publication gap. Reconciliation handles missing queue deliveries and stale worker leases; claims/publication use conditional state changes and attempt tokens. Retries are bounded. This behavior has contract tests, but live Redis/RQ recovery has not been exercised.
- Job creation snapshots garment revision, inputs, hashes, photo consent version and effective mock settings. Workers recheck owner/input/consent references and cancellation before publishing. Result/image reads are private and no-store.

## Privacy and deletion

- Cookie-authenticated unsafe requests require the session-bound CSRF token and an allowlisted Origin. Session cookies are HttpOnly, SameSite=Lax and Secure in production. Credentials are Argon2id-hashed; session and CSRF secrets are stored hashed. The SPA retains the CSRF token only in `sessionStorage`, not a bearer access token.
- Account, garment, person-photo and job deletions revoke database access first, delete job/attempt/outbox children in dependency order, and queue private-file cleanup. If file removal fails, the API returns `202 deletion_queued`; a cleanup worker retries from durable storage-deletion records.
- Local backend tests enable SQLite foreign-key enforcement and cover account, garment, photo and job deletion. Live PostgreSQL deletion behavior and concurrent deletion races remain unverified.

## Real FASHN and avatar contracts still open

- Selected candidate: pretrained FASHN VTON v1.5; requested profile is float16, 15 steps, guidance 1.5, seed 42, `segmentation_free=true`, `num_samples=1`. The inspected frozen source uses float32/BF16 and does not satisfy strict FP16. No application adapter or verified CUDA pose provider is present; real mode remains disabled.
- Before Gate B, verify exact source/model revisions, license terms, component precision, CUDA execution, finite output, private output handling, process-level timeout/recovery and representative consented result quality. Do not infer GPU readiness from an advertised provider or hardware inventory.
- Hybrid Avatar V1.4 source/material has not been found. Automatic photo initialization, neutral user correction, avatar persistence, downstream compatibility and intended DressMe use remain mandatory Gate C requirements, not implemented contracts.

## Verification scope

Backend unit tests use isolated SQLite, explicit BO6 mocks and a fake queue; BO6 has its own local regression suite. Offline PostgreSQL DDL generation and Compose configuration validation pass. None of these proves PostgreSQL, Redis/RQ, BO6/Compose service startup, browser end-to-end behavior, real FASHN output or avatar use. Exact latest commands and outcomes are in `AUTONOMOUS_EXECUTION_REPORT.md`.
