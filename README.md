# DressMe team application with private BO6/BO7 studio

The five original `rihab` sections remain in `static/index.html`. **My Studio** adds private garment, avatar and try-on pages. The team app remains FastAPI and plain HTML/CSS/JavaScript. The existing Python wardrobe backend is mounted at `/studio-api`; BO6 inference runs as a separate local service. Real BO7 web inference is not available in this migration. Mock jobs require Redis, dispatcher and worker.

## Windows local setup

From `D:\5eme\DressMe\projet_integration`:

```powershell
python -m venv --system-site-packages .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Restore only the two untracked BO6 weights from the existing verified source bundle or an equivalent checksum-matched backup. They are excluded from Git:

```powershell
Copy-Item 'D:\5eme\DressMe\Projet_DressMe\ml-service\bundle\model_weights.pt' 'bo6_service\bundle\model_weights.pt'
Copy-Item 'D:\5eme\DressMe\Projet_DressMe\ml-service\bundle\attribute_heads.pt' 'bo6_service\bundle\attribute_heads.pt'
.\.venv\Scripts\python.exe bo6_service\bundle\selftest.py
```

The bundle manifest in `bo6_service/bundle/checksums.json` checks both weights and all exported files at startup. The local check returned `passed=true`, `n_checks=17` on 29 October 2026. The baseline model is `E03_efficientnet_b0`, taxonomy `dressme-v0.2`.

Create a **separate** PostgreSQL cluster and database. The following example uses the locally installed PostgreSQL 18 and port 55461. Keep its password outside Git:

```powershell
$integrationRoot = Join-Path $env:LOCALAPPDATA 'DressMe\rihab-integration'
New-Item -ItemType Directory -Path $integrationRoot -Force | Out-Null
$pwFile = Join-Path $integrationRoot 'postgres.password'
if (-not (Test-Path $pwFile)) {
  $randomBytes = [byte[]]::new(24)
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
  [Convert]::ToHexString($randomBytes) | Set-Content -LiteralPath $pwFile -NoNewline
}
$pgData = Join-Path $integrationRoot 'postgres'
if (-not (Test-Path (Join-Path $pgData 'PG_VERSION'))) {
  & 'C:\Program Files\PostgreSQL\18\bin\initdb.exe' -D $pgData -U integration --pwfile=$pwFile --auth-host=scram-sha-256 --auth-local=trust
}
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D $pgData -l (Join-Path $integrationRoot 'postgres.log') -o '-p 55461 -h 127.0.0.1' start
$env:PGPASSWORD = Get-Content -LiteralPath $pwFile -Raw
& 'C:\Program Files\PostgreSQL\18\bin\createdb.exe' -h 127.0.0.1 -p 55461 -U integration dressme_integration
```

Run `createdb` only for a newly initialized cluster. On restart, start the existing cluster and keep its data.

In a PowerShell terminal at the repository root, configure the application and apply migrations:

```powershell
$integrationRoot = Join-Path $env:LOCALAPPDATA 'DressMe\rihab-integration'
$env:DATABASE_URL = 'postgresql+psycopg://integration:' + (Get-Content -LiteralPath (Join-Path $integrationRoot 'postgres.password') -Raw) + '@127.0.0.1:55461/dressme_integration'
$env:STORAGE_PATH = Join-Path $integrationRoot 'private-images'
$env:BO6_SERVICE_URL = 'http://127.0.0.1:18022'
$env:FRONTEND_ORIGINS = 'http://127.0.0.1:8002'
$env:VTON_MODE = 'mock'
$env:REDIS_URL = 'redis://127.0.0.1:6379/14'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8002
```

In a second terminal, from `bo6_service/`:

```powershell
$env:MODEL_BUNDLE_DIR = 'D:\5eme\DressMe\projet_integration\bo6_service\bundle'
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18022
```

Open [the local application](http://127.0.0.1:8002/#bo6-wardrobe). Check `/studio-api/health/ready` for `database=true`, `bo6_service=true`, `inference_mode=bo6_real`. The original five public pages do not need studio login.

The Avaturn creator is enabled only when `AVATURN_URL` is set to an approved HTTPS `*.avaturn.dev` origin without a path, port or query; add any separate exact HTTPS export origins to `AVATURN_EXPORT_ORIGINS`. Both are public configuration values, not credentials. The browser requires explicit photo-processing consent and checks provider message origin/frame identity and export URL origin. The existing provider account must accept `http://127.0.0.1:8002` before a local creator session can work. Its acceptance and real export remain unverified.

For mock try-on completion, provide a local Redis server at `127.0.0.1:6379`. In two more PowerShell terminals at the repository root, set the same `DATABASE_URL`, `STORAGE_PATH`, `REDIS_URL` and `TRYON_QUEUE_NAME` used by the application, then run:

```powershell
.\.venv\Scripts\python.exe -m app.tryon.dispatcher
.\.venv\Scripts\python.exe -m app.tryon.worker --simple-mock
```

Run one command per terminal. `--simple-mock` is the existing Windows development mode. Check `/studio-api/health/try-on` before submitting. The UI disables mock submission while that readiness endpoint reports unavailable. There is no automatic fallback from real to mock VTON.

Stop the two Uvicorn terminals with Ctrl+C. Stop only the dedicated PostgreSQL cluster with:

```powershell
$pgData = Join-Path (Join-Path $env:LOCALAPPDATA 'DressMe\rihab-integration') 'postgres'
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D $pgData stop
```

Persistent development data lives under `%LOCALAPPDATA%\DressMe\rihab-integration\postgres` and `private-images`. The repository does not contain user records, passwords, private photos, avatars or model weights.

## Verification

`scripts/verify_integration.py` runs a disposable two-account HTTP journey against the local stack and deletes only its own accounts. For application restart persistence, run `python scripts/verify_restart.py prepare`, restart only the application Uvicorn terminal, then run `python scripts/verify_restart.py finish`; its temporary credential file lives outside Git under the dedicated local data directory and is deleted after successful cleanup. `scripts/browser_check.cjs` exercises the original navigation and BO6 browser flow; set `DRESSME_PLAYWRIGHT_PATH` to an installed Playwright package and `DRESSME_BROWSER_EXECUTABLE` if its bundled browser is elsewhere. See `docs/INTEGRATION_VERIFICATION.md` for actual outcomes and limits.
