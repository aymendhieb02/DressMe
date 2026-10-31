# DressMe team setup (Windows, Python 3.11)

This checkout keeps the original five public sections, the combined FastAPI application and its plain HTML/CSS/JavaScript frontend. The Studio API is mounted under `/studio-api`; BO6 inference is a separate FastAPI process. The two Python services have separate locked environments because their FastAPI/Starlette pins differ. Setup never reads the original source checkout, installs no system packages, creates no database, applies no migrations and downloads no model weights.

## 1. Install prerequisites once

- Windows 10/11 and PowerShell.
- 64-bit Python 3.11 on `PATH` (`3.11.9` was used for the clean install check).
- Git.
- A running PostgreSQL server and its command-line tools (`createuser`, `createdb`, `psql`). The server installation path is not assumed.
- Optional: a reachable Redis server for MOCK queue jobs; optional Avaturn account/origin approval for the avatar creator.

The production/runtime requirements are pinned in `requirements.lock` and `bo6_service/requirements.lock`. Developer locks add `pytest` and are `requirements-dev.lock` and `bo6_service/requirements-dev.lock`. These locks were generated from successful isolated Python 3.11 installs; they are not shared between the application and BO6 services.

## 2. Clone or update

```powershell
git clone --branch integration_bo6_bo7 https://github.com/aymendhieb02/DressMe.git DressMe
Set-Location .\DressMe
.\scripts\dev\setup.ps1 -Developer -IncludeBo6
```

For an existing checkout:

```powershell
git pull --ff-only
.\scripts\dev\setup.ps1 -Developer -IncludeBo6
```

The setup script uses `.venv-app` and `.venv-bo6`, verifies that system site packages are disabled, and installs the corresponding lock files. It creates `.env` from `.env.example` only when `.env` does not exist. It never overwrites an existing `.env`. Keep credentials and local configuration in `.env`, which Git ignores.

## 3. Configure this machine

Create a dedicated PostgreSQL role and database. Run these commands once against the intended PostgreSQL server; `createuser` prompts for the role password without echoing it:

```powershell
createuser --host 127.0.0.1 --port 5432 --username postgres --pwprompt dressme_local
createdb --host 127.0.0.1 --port 5432 --username postgres --owner dressme_local dressme_local
```

Edit `.env` locally. Set these values for the dedicated database, a private persistent directory, and the chosen ports:

```dotenv
APP_PORT=8000
BO6_PORT=18022
DATABASE_URL=postgresql+psycopg://dressme_local:<URL-safe-password>@127.0.0.1:5432/dressme_local
STORAGE_PATH=<absolute-private-directory>/garments
EMAIL_CAPTURE_PATH=<absolute-private-directory>/mail-capture
PASSWORD_RESET_PEPPER=<unique-random-value-at-least-32-characters>
EMAIL_DELIVERY_MODE=capture
VTON_MODE=mock
REDIS_URL=redis://127.0.0.1:6379/0
```

The URL-safe database password avoids URI escaping errors. Do not use the example role/database for another project. The default script ports are configurable; use free ports and pass them to `start.ps1` and `check.ps1`. `start.ps1` sets the matching BO6 URL and frontend origin for its child processes. For private storage outside the checkout, use a directory under `%LOCALAPPDATA%` and create it before starting:

```powershell
$privateRoot = Join-Path $env:LOCALAPPDATA 'DressMe\Project_DressMe'
New-Item -ItemType Directory -Force -Path (Join-Path $privateRoot 'garments'), (Join-Path $privateRoot 'mail-capture') | Out-Null
```

Do not put passwords, reset codes, private image data or SMTP credentials in source files, screenshots or command history.

## 4. Restore the authorized BO6 artifacts

The exported bundle metadata and code are versioned. Its two `.pt` weights are intentionally excluded from Git. Obtain a trusted, already-exported bundle from an approved backup and provide its directory; no training, model download or source checkout is required:

```powershell
.\scripts\dev\restore-model-bundle.ps1 -SourceBundlePath 'X:\approved-backup\dressme-bo6\bundle'
```

The script checks both weights against this checkout's `bo6_service/bundle/checksums.json`, refuses to replace existing files, verifies the full manifest and runs the bundle self-test. If the weights already exist and match, it leaves them unchanged and runs verification. It does not modify the supplied source directory. BO6 startup also verifies the bundle manifest before serving `/health`.

The original public Style Engine and Find Similar routes have separate lazy CLIP/SigLIP downloads in the inherited application code (`laion2b_s34b_b79k`, Marqo FashionCLIP and Fashion-Product-baseColour). App setup does not fetch these weights. Their first model-assisted request can contact the upstream model hosts and populate the user's Python model cache. Those upstream artifacts do not have a repository-owned checksum/restore workflow yet; use those routes only when that download is expected and permitted. This does not affect BO6 inference, which uses only the restored, checksum-verified bundle.

## 5. Local email capture or SMTP

For local recovery tests, keep `EMAIL_DELIVERY_MODE=capture` and set `EMAIL_CAPTURE_PATH` to a private directory. Recovery messages are written there as `.eml`; treat them as secrets because they contain one-time codes. No email is sent externally. The test suite and browser script use disposable accounts.

For real mail, set `EMAIL_DELIVERY_MODE=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, and `SMTP_SECURITY=starttls` (or `ssl`) in the local environment. The application uses transport timeouts and does not log credentials or recovery codes. Production mode rejects recovery without a private 32+ character pepper and TLS-enabled SMTP. SMTP delivery is not verified by this setup guide.

## 6. Optional Avaturn configuration

The local GLB import and saved-avatar view do not require Avaturn. To enable the creator, set `AVATURN_URL` to the approved HTTPS creator URL and `AVATURN_EXPORT_ORIGINS` to the exact HTTPS origins allowed to provide exports. The API and browser enforce the provider/export origin checks. The provider account must authorize the app origin. PNG avatar rendering is not implemented; real provider initialization/export has not been verified on every teammate's origin.

## 7. Migrate, start, check and stop

Migrations are explicit. Review the configured database and migration state before applying updates:

```powershell
& .\.venv-app\Scripts\python.exe -m alembic current
& .\.venv-app\Scripts\python.exe -m alembic upgrade head
& .\.venv-app\Scripts\python.exe -m alembic current
```

Back up the dedicated database before applying a migration to a database with records. Then start the isolated BO6 service and application:

```powershell
.\scripts\dev\start.ps1 -AppPort 8000 -Bo6Port 18022
.\scripts\dev\check.ps1 -AppPort 8000 -Bo6Port 18022
```

Open `http://127.0.0.1:8000/#bo6-wardrobe`. `check.ps1` reports application/database readiness, BO6 model version and the optional queue separately. The application does not report ready unless the database and BO6 health checks pass. A Redis outage leaves core Studio and BO6 available but disables MOCK submission.

The starter records only the PIDs it creates under `%LOCALAPPDATA%\DressMe\Project_DressMe\runtime`; logs are stored there and never inside the repository. It refuses to stop an unrelated listener or PID. When no upload or mutation is in progress, stop those recorded services with:

```powershell
.\scripts\dev\stop.ps1
```

That command preserves the database, private images, captured mail and model weights. A service started manually in its own console should be stopped with Ctrl+C in that console. Never delete or reset another service's data directory.

## 8. Optional Redis/RQ MOCK jobs

Point `REDIS_URL` at a Redis instance already approved for local development. Use two separate PowerShell terminals from the repository root; `.env` is loaded by the Python application modules:

```powershell
& .\.venv-app\Scripts\python.exe -m app.tryon.dispatcher
```

```powershell
& .\.venv-app\Scripts\python.exe -m app.tryon.worker --simple-mock
```

Check `/studio-api/health/try-on` before creating a job. The worker produces MOCK preview artifacts only; no real VTON model runs. Cancellation, deletion and private-result APIs are present, but a live Redis job lifecycle remains unverified in this environment.

## Available without optional services

- The five original public team sections remain available.
- BO6 analyze, review, description, private wardrobe, edit and CSV export work when the checksum-valid BO6 bundle, PostgreSQL and the app are configured.
- Password recovery is testable through private local email capture; external delivery requires SMTP configuration.
- Avatar GLB import and saved-asset viewing are separate from Avaturn; creator setup requires an approved origin.
- Redis/RQ MOCK processing is unavailable until Redis, dispatcher and worker are reachable.
- Real BO7 virtual try-on and PNG avatar rendering are not available in this checkout.
