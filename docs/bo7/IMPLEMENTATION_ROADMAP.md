# BO7 incremental implementation roadmap

This sequence is based on the observed repository. It keeps BO6 inference as-is and adds BO7 to the same application. Phase 0 is the current audit/documentation work; GitHub publication is blocked until remote access and authentication can be checked.

## Phase 1 — Decide and verify shared application interfaces

- **Goal:** Establish backend/frontend/database/storage ownership and confirm the BO6-to-FASHN mapping before building shared infrastructure.
- **Reuse:** `ml-service/app/`, `ml-service/bundle/taxonomy.json`, root `ARCHITECTURE_ROADMAP.md`, this audit/contracts set.
- **Create/modify:** `docs/bo7/INTEGRATION_CONTRACTS.md`; no runtime code until decisions are recorded.
- **Contracts/dependencies:** Confirm candidate category mapping, garment review fields, identity and auth approach, private storage key behavior, and proposed shared stack.
- **Acceptance/evidence:** Written decisions with BO6 class coverage and explicit unsupported categories; inspect existing response schemas and taxonomy versions.
- **Commands:** `python -m pytest -q` from `ml-service`; `python -c "import json; print(json.load(open('ml-service/bundle/taxonomy.json'))['version'])"` from repository root.
- **Commit scope:** Phase 1 decision record only.
- **BO6 regression risk:** Low; do not touch the bundle or ML API.

## Phase 2 — Shared application backend foundation

- **Goal:** Add one FastAPI application backend, PostgreSQL, SQLAlchemy 2.x/Alembic, shared user/auth, and private storage.
- **Reuse:** Existing ML service remains a separate private service; root Compose becomes the stack integration point.
- **Create/modify:** `backend/` app/config/database/auth/storage/users/sessions, initial additive migration, tests, Dockerfile; root Compose and `.env.example`.
- **Contracts/dependencies:** Agreed cookie/token policy, owner-scoped SQL access, storage interface, explicit migration command.
- **Acceptance/evidence:** Register/login/refresh/logout/me, migration on clean DB, two-user isolation, private file access checks, service health and tests.
- **Commands:** Discover actual project commands after backend exists; expected `python -m pytest -q backend/tests` and `docker compose up --build` plus health checks.
- **Commit scope:** backend foundation + DB/storage/auth + Compose integration.
- **BO6 regression risk:** Keep ML endpoint unchanged; remove its host port only when backend can reach it internally and diagnostics remain documented.

## Phase 3 — Typed BO6 backend integration and garment API

- **Goal:** Provide authenticated analyze/review/describe/save/list/detail/update/delete flows backed by shared persistence.
- **Reuse:** ML service endpoints and schemas; preserve prediction snapshots and confirmed-value provenance.
- **Create/modify:** Backend ML client, garment/pending-upload models/services/routes, migration, ownership/contract tests.
- **Contracts/dependencies:** Phase 1 taxonomy mapping and Phase 2 auth/storage/database.
- **Acceptance/evidence:** Size/MIME/content validation, cleanup on inference failure, expiry/consume semantics, user A/B isolation, stable upstream error translation.
- **Commands:** Actual backend suite plus `python -m pytest -q ml-service`; no edits to `ml-service/bundle/`.
- **Commit scope:** BO6 orchestration and persistence only.
- **BO6 regression risk:** High at API boundary; test unchanged responses and taxonomy snapshots.

## Phase 4 — Unified React app and BO6 wardrobe flow

- **Goal:** Deliver one React + TypeScript + Vite app with auth, upload, prediction review, and wardrobe.
- **Reuse:** Shared backend contracts and user-confirmed garment data.
- **Create/modify:** `frontend/` routes, typed API client, auth state, accessible upload/review/wardrobe views and tests.
- **Contracts/dependencies:** Phase 2 auth and Phase 3 garment APIs.
- **Acceptance/evidence:** Register/login → upload → advisory quality → review → save → wardrobe; no direct ML calls, no score percentages, category/attribute eligibility honored.
- **Commands:** Discover npm scripts; expected frontend unit tests and production build.
- **Commit scope:** Frontend shared BO6 application shell and wardrobe.
- **BO6 regression risk:** UI must not change BO6 thresholds or classify `other` through ML.

## Phase 5 — BO7 mock adapter and API contract

- **Goal:** Add GPU-free asynchronous try-on job submission/status/result using a mock adapter.
- **Reuse:** Shared auth, garment/person storage references, selected garment and contract in `INTEGRATION_CONTRACTS.md`.
- **Create/modify:** BO7 schemas/routes/adapter and contract tests; preserve v1 idempotency/error envelope only after locating or recovering the existing mock API contract (none is in this checkout).
- **Contracts/dependencies:** Owner access, consent, photo type, supported mapping, job states, idempotency key semantics.
- **Acceptance/evidence:** Deterministic mock success/failure, duplicate key behavior, owner isolation, no fabricated progress, structured errors.
- **Commands:** Backend BO7 contract suite; frontend not required.
- **Commit scope:** Mock API and tests only.
- **BO6 regression risk:** Low; shared garment API remains stable.

## Phase 6 — Durable jobs, deletion, private media, and consent

- **Goal:** Persist job lifecycle, async queue, person-photo consent/upload, private result access, and deletion behavior.
- **Reuse:** Shared storage and owner-scoped records from Phase 2; mock adapter from Phase 5.
- **Create/modify:** Job/photo/result models and additive migrations, queue worker, cancellation/timeout handling, retention/deletion services, tests.
- **Contracts/dependencies:** Select Redis-backed queue and retention policy; define queued/running/completed deletion behavior.
- **Acceptance/evidence:** Restart-safe state, single initial inference concurrency, per-owner file checks, deletion of associated files, idempotency under retry.
- **Commands:** Backend tests and Compose service health; run deletion integration tests on disposable local data only.
- **Commit scope:** Queue, lifecycle, privacy controls.
- **BO6 regression risk:** Shared storage changes must preserve BO6 image access.

## Phase 7 — Person-photo and try-on UI, results, and history

- **Goal:** Add consent-first upload, photo selection, job state views, generated-image comparison, history, cancellation, and deletion in the same app.
- **Reuse:** Phase 4 app/auth/wardrobe and Phase 5/6 APIs.
- **Create/modify:** BO7 React feature routes/components and tests.
- **Contracts/dependencies:** Stable async APIs and private image endpoint.
- **Acceptance/evidence:** Explicit consent before upload; only named lifecycle states; accessible result preview and delete; show “Academic prototype — non-commercial” and “AI-generated preview, not an exact fit”.
- **Commands:** Frontend unit/integration tests and production build; backend contract suite.
- **Commit scope:** BO7 UI only.
- **BO6 regression risk:** Keep wardrobe selection and existing auth shared.

## Phase 8 — FASHN worker integration (no readiness claim)

- **Goal:** Integrate a separate process-isolated worker behind the adapter, with startup diagnostics and guarded real mode.
- **Reuse:** FASHN archive is research input only; inspect/extract into a tracked, licence-reviewed source package only after confirming archive integrity/rights.
- **Create/modify:** Worker image/service, adapter, health diagnostics, process timeout/isolation, provider/dtype checks and tests.
- **Contracts/dependencies:** Resolve 15-step vs archived 20/30-step mismatch; verify weights provenance and licences; GPU/CUDA/ONNX runtime.
- **Acceptance/evidence:** GPU-free mock remains; startup logs model revision/dtype/providers; real mode refuses float32 or CPU pose; serialized GPU access and killable timeout.
- **Commands:** Unit/contract tests on CPU; GPU checks are separate evidence and not inferred from unit tests.
- **Commit scope:** Worker and dependency/runtime files, excluding private weights.
- **BO6 regression risk:** Separate service boundary; no BO6 changes expected.

## Phase 9 — One real GPU smoke test

- **Goal:** Run one authorized smoke case on a clean GPU worker and record actual evidence.
- **Reuse:** Phase 8 worker and public sample inputs first; never use a real person's photo without consent.
- **Create/modify:** Smoke evidence record and operational notes only.
- **Contracts/dependencies:** Verified float16 path, CUDA DWPose providers, exact 15-step config, model/weight revision and license review.
- **Acceptance/evidence:** Real model output, actual ONNX providers, dtype, timings, peak GPU memory, hashes and success record; clean failure on unmet conditions.
- **Commands:** Worker smoke-test command from the chosen implementation; record exact command and output metadata without storing private images in Git.
- **Commit scope:** Sanitized evidence/documentation only.
- **BO6 regression risk:** None expected; test separately after any shared dependency changes.

## Phase 10 — Security and integration QA

- **Goal:** Verify owner isolation, consent, deletion, private media, error handling, and whole-app BO6/BO7 regressions.
- **Reuse:** All services and their tests.
- **Create/modify:** Fixes and QA documentation driven by findings.
- **Contracts/dependencies:** Licence/retention decisions and reproducible test environment.
- **Acceptance/evidence:** Full flows, privacy/deletion tests, Compose health, no public media paths, BO6 tests pass, real inference claims linked to smoke evidence.
- **Commands:** Actual backend/frontend suites, `python -m pytest -q ml-service`, `docker compose config`, and documented integration flows.
- **Commit scope:** Separate fixes by affected feature.
- **BO6 regression risk:** Medium; retain baseline test results and API schemas.

## Phase 11 — Hybrid Avatar V1.4 feasibility assessment

- **Goal:** Assess notebook provenance, dependencies, initialization, manual editing, persistence, privacy, and real-photo performance.
- **Reuse:** Existing notebook/report/archive only after integrity and license review.
- **Create/modify:** Feasibility report; no product code.
- **Contracts/dependencies:** Consent-based real-photo study protocol and product acceptance criteria.
- **Acceptance/evidence:** Reproducible notebook run plus documented real-photo validation plan; automatic initialization, manual editing, persistence, and product integration each marked proven/unproven.
- **Commands:** Notebook-specific commands discovered from the artifact; not yet known.
- **Commit scope:** Assessment document only.
- **BO6 regression risk:** None expected.

## Phase 12 — Validated Hybrid Avatar implementation

- **Goal:** Implement only the validated, accepted avatar scope in the shared application.
- **Reuse:** Phase 11 evidence and shared owner-scoped storage/auth.
- **Create/modify:** Small interfaces, persistence, UI, and tests established by assessment; do not assume notebook structure is production-ready.
- **Contracts/dependencies:** Phase 11 pass and explicit product decisions on editing, storage, and deletion.
- **Acceptance/evidence:** Initialization, manual correction, persistence/reload, owner isolation, consent/deletion and real-photo evaluation independently verified.
- **Commands:** Specify from actual chosen runtime; run feature and full application regression suites.
- **Commit scope:** Incremental avatar interface/persistence/product commits.
- **BO6 regression risk:** Shared identity/storage only; regression-test both modules.
