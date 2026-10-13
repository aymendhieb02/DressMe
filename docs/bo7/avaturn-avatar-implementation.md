# Avaturn private avatar flow

Status: implemented and covered by unit/API tests; live Avaturn export and provider-origin behavior remain unverified.

## Flow

1. An authenticated user sees the provider disclosure and explicitly consents before the embedded Avaturn creator is initialized.
2. The browser receives the SDK export event, imports the GLB from a `dataURL` or an explicitly allowed HTTPS export origin, and presents a separate review/save step. The browser never forwards the provider session ID or fetches arbitrary export hosts.
3. `PUT /avatars/current` checks the consent version and owner, enforces the upload cap, validates a self-contained GLB, and saves it through private local storage. A successful replacement switches the database reference before old-file cleanup.
4. `GET /avatars/current` and `GET /avatars/{id}/model` require the owner session. Model responses are private, uncached, and marked `nosniff`. The UI fetches the model with the session cookie and renders it through a dynamically loaded `<model-viewer>`.
5. Deleting an avatar or account removes the private GLB using the existing storage cleanup mechanism.

Avaturn photos are selected and submitted inside its embedded creator after the explicit notice. DressMe's saved wardrobe/person photos are not sent. The 3D model is a visual avatar only; it does not provide measurements or validated fit. No real provider export has been inspected in this environment, so the 50 MiB limit is provisional. If a real export uses a separate host, inspect its exact HTTPS origin and configure `VITE_AVATURN_EXPORT_ORIGINS` before rebuilding; arbitrary origins are rejected. No commercial-license clearance is claimed.

## Compose launch

The standard application URL is `http://localhost:8080`. From the repository root, after Docker Desktop's `desktop-linux` engine is available:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose --env-file .env config --quiet
docker compose --env-file .env run --build --rm backend alembic upgrade head
docker compose --env-file .env up --build -d
```

The migration adds `avatar_consents` and `avatars` at revision `0007_private_avatars`. `.env.example` uses the configured creator URL and leaves the export-origin allowlist empty. Stop with `docker compose --env-file .env down`; omit `-v` to retain PostgreSQL, Redis, and private storage volumes.

For Vite development, place public Vite settings in `frontend/.env.local` (the checked-in `frontend/.env.example` documents them). The dev proxy forwards `/avatars` to the API on port 8000. These Vite settings are public build configuration, never credentials.

In the current session, `http://localhost:5173` is running against the local API at port 8000 and a fresh SQLite database/private-storage directory under `%TEMP%\DressMe-Avatar-Demo-419dd156051f4c2680d818369727b9fb`. This isolated account store contains no imported user data. The API liveness endpoint is 200; readiness is 503 because BO6 is not running. Authentication and avatar routes are available, while BO6-dependent wardrobe analysis and Redis/RQ worker jobs are not. Register or sign in through the app to try the consent and avatar flow. The normal Docker Compose URL remains `http://localhost:8080` after Docker access is restored.

## Validation evidence and limits

- Synthetic 476-byte triangle GLB: parser acceptance, malformed/truncated data and external-resource rejection covered by tests.
- Backend API tests cover explicit consent/CSRF, owner-only model retrieval, idempotent export, safe replacement, deletion, account cleanup, and migration.
- Frontend tests cover consent-before-init, export review before save, session-free provider payload handling, and retaining a retryable export after failed storage.
- Actual iframe initialization, provider photo processing, real GLB export size/origin, physical-device interaction, and actual browser-to-database storage have not been verified.
- A successful API/test response is not evidence of a real Avaturn generation.
