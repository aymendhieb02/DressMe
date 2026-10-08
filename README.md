# DressMe BO6 — Smart Wardrobe Digitization

BO6 is a single-garment photo workflow for a digital wardrobe. Its AI suggests a garment category and eligible attributes; users review and confirm the values before they are saved. The bundle's scores are uncalibrated and are not probabilities. The model was validated on catalogue images; its performance on real phone photos has not yet been measured.

## Target architecture

- **Frontend:** React, TypeScript, Vite.
- **Application backend:** Python FastAPI; authentication, authorization, application APIs, and orchestration.
- **ML service:** the existing Phase 1 Python FastAPI service, unchanged and private to the Docker network.
- **Database:** PostgreSQL through SQLAlchemy 2.x and Alembic migrations.
- **Image storage:** private local disk behind a storage abstraction, persisted by a Docker volume.
- **Deployment:** Docker Compose.

The frontend talks only to the application backend. The application backend calls the ML service over the internal Docker network. PostgreSQL and the ML service are not published to the host in the completed stack.

The repository now contains the shared application API and BO6 wardrobe workflow under `backend/`, a React/Vite client under `frontend/`, and a Compose topology for PostgreSQL, private BO6 inference, Redis, an outbox dispatcher, a separate mock worker, backend, and frontend. Local API tests use isolated SQLite and mock BO6/queue contracts; a separate real BO6 + SQLite wardrobe smoke was verified. PostgreSQL and Compose runtime remain unverified because the Docker Linux engine is inaccessible. See the [authoritative execution report](docs/DRESSME_AUTONOMOUS_EXECUTION_REPORT.md) for exact evidence and remaining acceptance gates.

See [ARCHITECTURE_ROADMAP.md](ARCHITECTURE_ROADMAP.md) for the exact proposed project structure, migration plan, API flow, and acceptance criteria for Phases 1–6.

## Phase 1 ML service

The Phase 1 service wraps the exported BO6 model bundle. The bundle is treated as immutable. At startup, the service checks its manifest, loads one CPU model per process, and serializes prediction calls because the model keeps mutable hook state.

#### Model checkpoint assets

The checkpoint files `ml-service/bundle/model_weights.pt` and `ml-service/bundle/attribute_heads.pt` are excluded from Git because redistribution rights have not been established. Obtain the matching export from the project owner or an approved private artifact before building or starting the ML service. The expected paths, manifest verification, and missing-artifact behavior are documented in [ml-service/ARTIFACTS.md](ml-service/ARTIFACTS.md). The private archive currently present in this local workspace is not published.

Place those two checkpoint files at the exact paths under `ml-service/bundle/`, then verify their SHA-256 values against `ml-service/bundle/checksums.json`. Do not substitute checkpoints from another model export. Docker build and service startup intentionally fail if files are absent or fail checksum validation. The source archive and weights are not published in this Git repository.

The BO7 FASHN inference source and license files are kept under `BO7 — Try-On/AvatarProfile/dressme_bo7_fashn_inference_v1/`. Its pretrained weights are also excluded from Git: the local offline archive is `BO7 — Try-On/AvatarProfile/dressme_bo7_fashn_weights_offline_PRIVATE.zip` (about 2.4 GB). Obtain an authorized copy from the project owner or approved project artifact, then use the package's `tools/restore.py --offline-weights <archive>` command to restore and verify hashes into a private runtime weights directory. Do not commit the archive or restored checkpoints.

From the repository root:

```bash
cd ml-service
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bundle/selftest.py
pytest -q
uvicorn app.main:app --reload --port 8000
```

For local integrated development, first restore the authorized BO6 checkpoints described above. Then copy the placeholder environment file once, validate Compose, run migrations, and start the application:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose --env-file .env config --quiet
docker compose --env-file .env run --build --rm backend alembic upgrade head
docker compose --env-file .env up --build -d
```

Open `http://localhost:8080`. The application backend is available on `http://localhost:8000` for local API development. PostgreSQL and the BO6 ML service are not published to the host; the backend calls the ML service privately. The PostgreSQL and private-image volumes persist across restarts. Use `docker compose down` for ordinary shutdown; omit `-v` so persistent data remains.

For a Vite development server instead of the Compose frontend, run `npm ci` and `npm run dev` from `frontend/`. Its `/auth`, `/garments`, `/person-photos`, `/try-on`, and `/health` requests proxy to the application backend at `localhost:8000`.

To run the backend unit suite locally, create a virtual environment in `backend/`, install `requirements-dev.lock`, and run `python -m pytest tests -q`. These tests use an isolated SQLite database and explicit BO6/queue mocks where needed; use Compose with a disposable PostgreSQL database for PostgreSQL acceptance.

The try-on screen is explicitly mock-only. It returns a labelled contact sheet of the two source photos; it does not generate an outfit or estimate fit. The project remains an academic prototype; component and dataset terms vary, and this notice is not commercial-use clearance.

The local automated checks are `python -m pytest ml-service/tests -q`, `backend/.venv/Scripts/python.exe -m pytest backend/tests -q` (after installing `backend/` dependencies), `npm ci`, `npm test`, and `npm run build` from `frontend/`. SQLite and mocked BO6 tests are development evidence only; they do not establish PostgreSQL migration or integrated real-service acceptance.

### ML endpoints

- `GET /health` returns the model, taxonomy, description, and quality versions from the bundle.
- `POST /analyze` accepts a JPEG, PNG, or WEBP image up to 10 MB as multipart field `image`; it returns the bundle prediction unchanged alongside advisory quality results.
- `POST /describe` regenerates a description from confirmed fields using the bundle's deterministic template; it does not need an image and rejects `other`.

Corrupt images return structured 422 errors, oversized images return 413, and unsupported media types return 415. Quality warnings do not block inference. AI suggestions require user review.

## Scope boundaries

BO6 covers one uploaded garment at a time, classification and structured description, user review/correction, and wardrobe storage. BO7 virtual try-on, avatars, recommendations, OCR, segmentation, and multi-garment detection are outside BO6.
