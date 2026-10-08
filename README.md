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

The repository is currently at Phase 1. It contains the ML service, BO6 source materials, and BO7 research materials. It does not yet contain the React frontend, application backend, or PostgreSQL stack. The current Phase 1 Compose file publishes the ML diagnostic port on host port 8001; the future application Compose topology will remove that host mapping while preserving the ML service itself.

See [ARCHITECTURE_ROADMAP.md](ARCHITECTURE_ROADMAP.md) for the exact proposed project structure, migration plan, API flow, and acceptance criteria for Phases 1–6.

## Phase 1 ML service

The Phase 1 service wraps the exported BO6 model bundle. The bundle is treated as immutable. At startup, the service checks its manifest, loads one CPU model per process, and serializes prediction calls because the model keeps mutable hook state.

#### Model checkpoint assets

The checkpoint files `ml-service/bundle/model_weights.pt` and `ml-service/bundle/attribute_heads.pt` are excluded from ordinary Git history. The remaining bundle source, metadata, and `checksums.json` are kept in the repository. Before running the ML service from a fresh clone, obtain the matching exported BO6 bundle archive from the project owner or approved project artifact. In the current local project it is `BO6 — Smart Wardrobe Digitization/final_v2/selected_model_bundle.zip`.

Place those two checkpoint files at the exact paths under `ml-service/bundle/`, then verify their SHA-256 values against `ml-service/bundle/checksums.json`. Do not substitute checkpoints from another model export. Docker build and service startup intentionally fail if files are absent or fail checksum validation. The source archive and weights are not published in this Git repository.

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

For the Phase 1 development diagnostic container:

```bash
docker compose build ml-service
docker compose up -d ml-service
curl http://localhost:8001/health
```

The current host port is temporary development access. The completed multi-service Compose stack will make the ML API reachable only to the application backend over Docker networking.

### ML endpoints

- `GET /health` returns the model, taxonomy, description, and quality versions from the bundle.
- `POST /analyze` accepts a JPEG, PNG, or WEBP image up to 10 MB as multipart field `image`; it returns the bundle prediction unchanged alongside advisory quality results.
- `POST /describe` regenerates a description from confirmed fields using the bundle's deterministic template; it does not need an image and rejects `other`.

Corrupt images return structured 422 errors, oversized images return 413, and unsupported media types return 415. Quality warnings do not block inference. AI suggestions require user review.

## Scope boundaries

BO6 covers one uploaded garment at a time, classification and structured description, user review/correction, and wardrobe storage. BO7 virtual try-on, avatars, recommendations, OCR, segmentation, and multi-garment detection are outside BO6.
