# DressMe BO6 Architecture and Implementation Roadmap

## Architecture decision

Use one browser application and two separate Python services:

```text
React + TypeScript + Vite
            │ same-origin API / configured backend URL
            ▼
Application backend: FastAPI + SQLAlchemy 2.x + Alembic
            ├── PostgreSQL
            ├── private local image storage
            └── internal HTTP ──► existing Phase 1 FastAPI ML service
```

PostgreSQL, private image storage, and the ML service are not public browser-facing services. Only the frontend and application backend need host-facing ports for local development. In the completed Compose topology, the backend calls `http://ml-service:8000` on a private Docker network. The React client never calls the ML service directly.

### Technology decisions

| Concern | Selected technology | Boundary |
|---|---|---|
| Frontend | React, TypeScript, Vite | Browser UI and typed application-backend client |
| Application API | Python FastAPI | Authentication, authorization, validation, orchestration, garment APIs |
| ML inference API | Existing Python FastAPI service | Existing bundle wrapper; retained unchanged |
| Database | PostgreSQL | Durable users, sessions, pending uploads, garments |
| ORM and migrations | SQLAlchemy 2.x, Alembic | Python persistence layer and versioned schema changes |
| Image storage | Private local disk behind a storage interface | Opaque keys; never served as a public static directory |
| Local orchestration | Docker Compose | Frontend, backend, ML service, PostgreSQL, and persistent storage volume |

NestJS and Prisma are removed from the planned architecture. They are not present in the current repository, so there is no working implementation to delete or migrate.

## Repository audit and current conflicts

The workspace currently contains `ml-service/`, BO6 research/project materials, BO7 research materials, and a root README/Compose file. It has no `backend/`, `frontend/`, PostgreSQL service, SQLAlchemy models, or Alembic migrations. Therefore Phases 2–6 are plans, not existing implementations.

The Phase 1 Compose file currently publishes the ML diagnostic API on host port 8001. That is useful for Phase 1 diagnostics but conflicts with the final private-service topology. Phase 2/6 Compose work must remove the ML host `ports` mapping and let only the backend reach `ml-service:8000` internally. This roadmap update does not change that working Phase 1 service or its Compose file.

The exported bundle under `ml-service/bundle/` is immutable. Do not edit, reformat, regenerate, or replace its files as part of later phases. Validate it against its own `checksums.json` and run its `selftest.py` as already required by Phase 1.

## Exact proposed project structure

```text
.
├── ARCHITECTURE_ROADMAP.md
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── package-lock.json
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── api/                 # typed backend client, errors, token-aware requests
│       ├── auth/                # auth state, route guards, login/register forms
│       ├── components/          # shared accessible UI
│       ├── features/
│       │   ├── upload/
│       │   ├── review/
│       │   └── wardrobe/
│       ├── hooks/
│       ├── pages/
│       ├── types/
│       └── tests/               # component and frontend integration tests
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml            # FastAPI, SQLAlchemy, Alembic, auth, HTTP client
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/             # reviewed, additive schema migrations
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py           # SQLAlchemy engine, session factory, Base
│   │   ├── api/
│   │   │   ├── router.py
│   │   │   └── dependencies.py
│   │   ├── auth/
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   ├── security.py
│   │   │   └── dependencies.py
│   │   ├── users/
│   │   │   ├── models.py
│   │   │   └── service.py
│   │   ├── sessions/
│   │   │   └── models.py          # RefreshSession
│   │   ├── uploads/
│   │   │   ├── models.py          # PendingUpload
│   │   │   ├── schemas.py
│   │   │   └── service.py
│   │   ├── garments/
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   ├── router.py
│   │   │   └── service.py
│   │   ├── storage/
│   │   │   ├── interface.py
│   │   │   └── local_disk.py
│   │   ├── ml/
│   │   │   ├── client.py
│   │   │   ├── schemas.py
│   │   │   └── errors.py
│   │   ├── health/
│   │   │   └── router.py
│   │   └── common/
│   │       ├── errors.py
│   │       ├── logging.py
│   │       └── middleware.py
│   ├── scripts/
│   │   └── export-training-pairs.py
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── e2e/
├── ml-service/                   # Phase 1 service; keep its implementation unchanged
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   ├── tests/
│   └── bundle/                   # exported model files; immutable
└── data/                          # local runtime data; gitignored
    └── private-images/           # mounted only into backend
```

`data/private-images/` is runtime storage, not committed source. In Compose it is a named or bind-mounted persistent volume accessible only to the backend. The exact package/lock files may follow the chosen package manager, but the frontend remains React + TypeScript + Vite.

## Data model requirements

Use SQLAlchemy 2.x declarative models and PostgreSQL UUID, JSONB, timestamp, uniqueness, foreign-key, and index support. Preserve these application concepts and fields; use idiomatic Python column names internally if desired, while keeping the API contract stable.

### User

```text
id UUID primary key
email unique
passwordHash
role USER | ADMIN
createdAt
updatedAt
```

Store only a strong one-way Argon2id or bcrypt password hash. Never log passwords or tokens.

### RefreshSession

```text
id UUID primary key
userId FK → User
tokenHash
expiresAt
revokedAt nullable
createdAt
```

Store a hash of the refresh token, never its raw value. Rotation, revocation, expiry checks, and replay handling must be transactional.

### PendingUpload

```text
id UUID primary key
userId FK → User
imageKey
qualitySnapshot JSONB
predictionSnapshot JSONB
modelVersion
taxonomyVersion
descriptionVersion
qualityVersion
expiresAt
consumedAt nullable
createdAt
```

### Garment

```text
id UUID primary key
userId FK → User
imageKey
category
color
pattern
sleeveLength
description
name nullable
notes nullable
predictionSnapshot JSONB
qualitySnapshot JSONB
fieldSources JSONB
wasCorrected JSONB
modelVersion
taxonomyVersion
descriptionVersion
createdAt
updatedAt
```

Add indexes for `userId`, `(userId, category)`, `(userId, color)`, and `createdAt`. All reads and mutations of user-owned records must include the authenticated user ID in the database predicate; do not load by resource ID and authorize afterward.

## Authentication and security contract

- `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, and `GET /auth/me`.
- Short-lived access JWT returned to the SPA and held in memory.
- Rotating refresh token in an HttpOnly cookie; Secure in production and an appropriate SameSite policy.
- Hash refresh tokens at rest. Rotation invalidates the previous session token; logout revokes its session.
- Never log credentials, tokens, image bytes, or full personal payloads.
- Validate DTOs and image content; upload limit is 10 MB, with JPEG/PNG/WEBP accepted. HEIC must be converted by the client before upload.
- Private authenticated image reads; opaque storage keys; no public static mount for uploaded images.
- Restrict CORS to configured frontend origin; return stable errors without internal stack traces.
- Rate limit authentication and image analysis routes in the completed application.

## Phase roadmap

### Phase 1 — ML service and Docker: implemented

Keep the current `ml-service/` implementation and bundle unchanged. Its service loads one CPU model per process, validates checksums, runs the bundle self-test in Docker build, serializes prediction calls, exposes `/health`, `/analyze`, and `/describe`, and has regression coverage for uploads, descriptions, and concurrency.

The current host-published ML port is diagnostic only and is removed from the final application Compose topology in a later phase. No Phase 1 source change is required for this architecture decision.

### Phase 2 — FastAPI application backend, database, auth, and private storage

Create `backend/` as a separate FastAPI application. Add PostgreSQL, SQLAlchemy 2.x models, Alembic migrations, the four preserved data models, auth/session rotation, authenticated-user dependencies, private local storage abstraction, backend/DB health, Dockerfile, and Compose integration. An ML client may exist as a typed skeleton or health probe, but garment analysis is not integrated in this phase.

Use Alembic migrations as an explicit development initialization step or documented entrypoint. Do not run destructive production migrations automatically at application startup.

**Exit checks:** registration and duplicate registration; valid/invalid login; refresh rotation; logout/revocation; protected route and `/auth/me`; two-user isolation; storage keys and private access; migrations apply cleanly; backend build/tests pass; PostgreSQL and backend start and report health.

### Phase 3 — Python ML integration and complete garment API

Implement a typed application-backend ML client using Python HTTP communication (for example, `httpx`). Configure `ML_SERVICE_URL`, connect/read timeouts, stable error translation, and calls to ML `/health`, `/analyze`, and `/describe`. The service URL in Compose is internal (`http://ml-service:8000`); do not publish the ML port to the host in the full stack.

Implement authenticated `POST /garments/analyze` (validate, private store, analyze, create owner-scoped `PendingUpload`), `POST /garments/describe` (verify upload ownership and use confirmed fields), `POST /garments` (consume an unexpired pending upload transactionally and persist provenance/snapshots), and owner-scoped list/detail/update/delete/image endpoints. If ML analysis fails permanently, remove the newly stored image. Preserve prediction scores and snapshots exactly; do not recalculate thresholds or send `other` as an ML category.

**Exit checks:** API contract tests, timeout/error mapping, upload cleanup, expiry/consumption, ownership checks across all endpoints, and mandatory user A/user B isolation tests.

### Phase 4 — React upload, quality, and review flow

Build the mobile-first React + TypeScript + Vite app in `frontend/`. Add login/register screens, in-memory access token handling and refresh restoration, camera/file upload, preview, client-side resizing, HEIC conversion or a clear conversion error, upload cancellation where practical, and 413/415/422/503/network handling.

Implement the flow `login → upload → quality → review → save`. Treat quality warnings as advisory with Retake and Continue anyway. On review, follow returned `description_fields` and `attributes.*.eligible`; never independently calculate the category threshold. Show both category suggestions; do not preselect when category is withheld. Colour starts unconfirmed and only enters description after explicit selection. Do not display model scores as percentages. Map “Not listed” to application category `other`, but never send `other` to the ML service. Debounce deterministic description previews. Keep `name` and `notes` separate and do not let the client forge provenance or prediction snapshots. After save, route to `/wardrobe` placeholder.

Keep accessible labels, keyboard behavior, focus, contrast, and field-associated errors. Include an AI-review notice.

**Exit checks:** component tests for confident/withheld category, second suggestion, hidden ineligible attributes, unconfirmed colour, description refresh after colour choice, no percentage score, `other` mapping, and advisory Continue anyway; mocked upload→warning→continue→review→save integration test; frontend tests and production build.

### Phase 5 — Wardrobe, editing, export, and product polish

Add responsive wardrobe grid, category/colour filters, pagination, loading/empty/error states, garment detail, edit through shared review components, confirmed deletion, private authenticated image access, success/error feedback, route guards, 404 route, and mobile-width polish.

Add an admin-only training-pair export preserving image reference, original prediction snapshot, confirmed values, field sources, correction flags, model/taxonomy/description versions, and timestamps. Never export credentials or merge predicted and confirmed values.

**Exit checks:** wardrobe/filter/pagination tests, detail/edit/delete/image/route-guard tests, plus full register/login→upload→analyze→review→save→wardrobe→detail→edit→refresh→delete e2e. Run the export and inspect a sample row. Do not claim real-phone accuracy without that experiment.

### Phase 6 — Final QA, security, Compose, and documentation

Harden the complete Compose stack: frontend, application backend, private ML service, PostgreSQL, and persistent private image storage. Add health checks, internal networking, sensible dependencies, and documented clean setup. Publish only browser-facing development ports; do not publish PostgreSQL or ML.

Audit token hashing/rotation, ownership predicates, path traversal, opaque keys, MIME/content checks, size limits, auth/analyze rate limiting, authenticated images, CORS, production cookie security, DTO validation, safe errors, and privacy-safe structured logs. Verify the ML service still checks bundle checksums, loads one CPU model, locks predictions, passes self-test, preserves score semantics, and leaves the bundle unchanged.

**Exit checks:** all ML/backend/frontend unit and e2e suites; Compose build/start/status; health of all services; real supported API flow including garment CRUD; export validation; README setup and limitations. Clearly state catalogue-only evaluation, unmeasured phone-photo performance, uncalibrated scores, and required user review.

## Target Compose topology and environment

Final Compose services:

```text
frontend ──► backend ──► postgres
                  └────► ml-service (private network only)
                  └────► private image volume
```

Configuration includes `DATABASE_URL`, `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, access/refresh TTLs, `STORAGE_DRIVER`, `STORAGE_PATH`, internal `ML_SERVICE_URL`, and `FRONTEND_ORIGIN`. Provide only placeholders in `.env.example`; keep `.env` out of version control. PostgreSQL data and backend-owned images use persistent volumes. Backend startup waits for database health; migrations are run explicitly in the documented developer workflow.

## Phase 1 files to preserve

Do not edit files under `ml-service/bundle/` or change the model behavior while building later phases. Keep Phase 1 API contracts stable. Changes to root `docker-compose.yml` in Phase 2/6 are allowed to integrate the other services and privatize the ML network; they must not alter the ML application or bundle.
