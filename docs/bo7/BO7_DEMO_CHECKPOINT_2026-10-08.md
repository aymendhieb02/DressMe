# BO7 bounded demonstration checkpoint — 2026-10-08

## Outcome and scope

**Outcome: INCOMPLETE — useful integration fixes implemented and tested; the live Redis/RQ/browser result remains blocked.**

The session started at 11:35 UTC on `feature/bo7-autonomous-mvp`, revision `d2f1f22`. Infrastructure investigation ended by 11:40 UTC, within the requested ten-minute limit. No Docker/WSL permissions, system security settings, packages or GPU runtimes were changed. The supplied BO7 engineer skill ZIP and project engineering checklist were applied; the separate named Project Engineer SKILL.md was unavailable. No UI redesign, BO6 contract change, training, model selection or Hybrid Avatar work was performed.

The successful output exercised in this session is **mock**: the existing worker creates a labelled 1000×680 contact sheet of the two source photos. Offline API tests execute that worker function and retrieve its PNG from private test storage. No new output was displayed in a browser, no live Redis delivery occurred, and no FASHN inference ran. Passing these tests establishes contracts and the reproduced recovery cases, not an end-to-end demonstration or complete Gate A acceptance.

## Inspected state and findings

- The authoritative `docs/DRESSME_AUTONOMOUS_EXECUTION_REPORT.md` and Git state were read first. The report already had uncommitted appendices, and the BO7 project-summary PDF was untracked. Both are preserved and excluded from the local commit.
- Inspected `backend/app/tryon/{router,schemas,dispatcher,worker,worker_tasks}.py`, database models/configuration, private storage boundaries, existing backend tests, `docker-compose.yml`, `.env.example`, and the existing frontend polling/result code. The API→outbox→JSON RQ delivery→mock result→private retrieval→UI display path was already implemented in source.
- **CONFIRMED:** SQLite reloads the persisted timestamp columns without timezone information. Dispatcher delivery/lease age calculations mixed those values with aware UTC timestamps, raising `TypeError` and preventing the loop from reaching subsequent work. The new tests reproduced this before the fix.
- **CONFIRMED:** recovery could overwrite a worker's successful publication using stale ORM state. Tests reproduced both a stale running-attempt recovery and stale queued cancellation, then verified that publication survives the fixes.
- **CONFIRMED:** dispatcher and direct worker delivery lacked persisted mode/adapter checks, despite the API rejecting real mode. An unsupported or future real profile could enter the mock path. Tests reproduced unsupported dispatch and now require an explicit terminal error with no mock substitution.
- Installed RQ 2.12 source uses Unix process APIs for its isolated Worker. Its SpawnWorker also retains Unix-specific process operations. Selecting SpawnWorker alone would not establish native Windows support. The opt-in SimpleWorker path avoids per-job forking, with its reduced isolation stated explicitly; actual broker execution on Windows remains **NOT VERIFIED**.
- Separate frontend edits appeared during the session in `frontend/src/{App.tsx,App.test.tsx,api.ts,styles.css}`. They were preserved and excluded from this worker commit. A final test/build pass covered a stable snapshot of those files; SHA-256 values below identify it.

## Implemented changes and compatibility

- `backend/app/tryon/adapters.py`: shared predicate permits only persisted `mode=mock`, snapshot `mode=mock`, and adapter `mock-preview-v1`. Unsupported profiles fail with `unsupported_vton_adapter` at dispatch and direct delivery boundaries, before private image access or result generation.
- `backend/app/tryon/dispatcher.py`: normalize loaded timestamps to UTC. Recovery/cancellation use conditional database updates matching the original state; running recovery also matches the original attempt token and timestamp. Attempt/outbox changes happen only if that update wins, preserving concurrent successful publication. Queued cancellation checks its state alone, preserving SQLite server-default timestamp compatibility.
- `backend/app/tryon/worker.py`: explicit development/test-only `--simple-mock`, plus `--burst` and positive `--max-jobs` options; broker ping/cleanup and readable startup failures. Native Windows default startup fails before broker access and directs the operator to Linux/Compose or the explicit simple mock option. Real mode fails closed. Linux/Compose retains the existing isolated Worker and JSON queue serialization.
- `backend/app/tryon/worker_tasks.py`: validate the persisted adapter profile before storage initialization/access. Existing labels, ownership checks, cancellation and duplicate-claim tokens are retained.
- `backend/tests/test_tryon_dispatcher.py`: twelve offline cases cover missing deliveries, SQLite leases/server-default timestamp compatibility, terminal cancellation/exhausted attempts, unsupported profiles and the two publication races.
- `backend/tests/test_tryon_worker.py`: twelve cases cover stale unsupported deliveries, bounded worker selection/options, rejected startup configurations, broker startup failure and owner-only successful result retrieval.
- `backend/tests/conftest.py` and `backend/tests/test_auth.py`: each isolated API fixture receives a fresh process-local login limiter with unchanged configured limits; a threshold test proves HTTP 429 enforcement remains active. This fixes test cross-contamination, not production authentication.
- `docs/bo7/IMPLEMENTATION_STATUS.md` and this checkpoint record the evidence and limits. No schema migration, dependency change or public API field change is required. Existing unsupported profiles now terminate explicitly instead of entering the mock adapter.

## Exact validation and failures

Commands below use the stated working directory. Passing commands returned exit 0, with zero failed/skipped tests.

| Working directory / command | Result and evidence limit |
|---|---|
| repository / `docker context show` | `desktop-linux`. |
| repository / `docker info --format '{{.ServerVersion}}'` | Exit 1: `open //./pipe/dockerDesktopLinuxEngine: Access is denied`. One engine check; no permission workaround. |
| repository / `docker compose --env-file .env.example config --quiet` | Exit 0 on final configuration validation. No engine contact/container startup. |
| repository / `docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example config --format json` with the launch guide's environment | Exit 0; backend `127.0.0.1:18080`, frontend `127.0.0.1:18081`, private volume `dressme-bo7-mock-demo-20261008_private_images`. Configuration only. |
| repository / `Get-Command redis-server,redis-cli -ErrorAction SilentlyContinue` and `Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue` | Neither executable nor listener was available. No Redis service was started. |
| repository / `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader` | Exit 0: RTX 3050 Laptop GPU, 4096 MiB, driver 576.88. Capacity only; no inference peak VRAM measurement. |
| repository / `python -c "import torch; print('torch=',torch.__version__); print('cuda_available=',torch.cuda.is_available()); print('cuda_build=',torch.version.cuda)"` | Exit 0: Torch `2.11.0+cpu`, CUDA false, CUDA build None. |
| backend / `.\.venv\Scripts\python.exe -m pytest tests/test_tryon_dispatcher.py -q` before original fixes | Seven failures reproduced timestamp/profile gaps. After the first fixes: seven passed. |
| backend / `.\.venv\Scripts\python.exe -m pytest tests/test_tryon.py tests/test_tryon_dispatcher.py tests/test_tryon_worker.py -q` | Initial combined run: 17 passed, five failed (exit 1). All five failures were synthetic registration HTTP 429 from shared test limiter state; no assertions were weakened. |
| backend / `.\.venv\Scripts\python.exe -m pytest tests -q` after fixture/profile fixes | 43 passed, two existing deprecation warnings; exit 0. Subsequent recovery regressions justified the final rerun below. |
| backend / `.\.venv\Scripts\python.exe -m pytest tests/test_tryon_dispatcher.py -q` before running-race fix | Nine passed, one failed (exit 1): recovery overwrote successful publication. After its fix, ten passed. |
| backend / `.\.venv\Scripts\python.exe -m pytest tests/test_tryon_dispatcher.py::test_completed_mock_wins_over_stale_queued_cancellation_status -q` before queued-race fix | One failed (exit 1), reproducing successful result overwritten by stale cancellation. |
| backend / `.\.venv\Scripts\python.exe -m pytest tests/test_tryon_dispatcher.py::test_queued_cancellation_preserves_sqlite_server_default_timestamp_behavior -q` before final compatibility fix | One failed (exit 1): timestamp equality prevented legitimate cancellation of a fresh SQLite job. State-only queued cancellation preserves both ordinary cancellation and concurrent completion. |
| backend / `.\.venv\Scripts\python.exe -m pytest tests -q` final | **48 passed**, two existing deprecation warnings; exit 0. SQLite/API tests, direct worker execution, explicit fake Redis/RQ boundaries. |
| backend / `.\.venv\Scripts\python.exe -m app.tryon.worker --help` | Exit 0; shows `--simple-mock`, `--burst`, `--max-jobs`. No broker contact. |
| frontend / `npm test` | Sandbox startup initially exited 1 with esbuild `spawn EPERM`; no test assertion ran. Approved retry passed eight tests. After concurrent frontend edits, final approved run: **11 passed**, zero failed/skipped, exit 0. |
| frontend / `npm run build` final | Exit 0: TypeScript check + Vite production build; 30 modules. |
| repository / `git diff --check` | Exit 0. Git's LF/CRLF notices are conversion warnings, not whitespace errors. |

The two final backend warnings concern Starlette/httpx TestClient use and per-request cookies in an existing auth test. Their occurrence was also recorded before this session; they are not introduced by the worker changes. BO6 tests/bundle self-test were not rerun because no BO6 code or contracts changed; historical results remain in the authoritative report.

Preservation checks retain the report's pre-session 30,918-byte prefix exactly (SHA-256 `0491f04738d68272d8cec63e9d0f9c569f44926c123dcc479f4600b2dd2ffc60`); the new continuation is appended, and the report remains unstaged. The untracked PDF remains byte-identical (SHA-256 `e6ac7589675adc17afcfbef630cace8fbf8b19157f04fb2a01df553015fe8cf4`). Separate frontend edits remain outside this commit.

Stable frontend snapshot during final validation:

```text
App.tsx       11be8fb60dc8cd8739681f3df03cfb8cec6b9453069d976d55d00ffcda57591f
api.ts        1aa14241eaa15bed03cd59d33f61e65dbf322852ed06411fde1b3bde21f3645c
App.test.tsx  aeb4481366c6cb0284b5e20c02bafbb89ebec88b8f8301994ff04533ad0e3b33
styles.css    4a90c3da183b8fedf677b05c546dd581d22f51fc3b16d94084bc30f795100e83
```

## Launch the existing mock demonstration after runtime access is restored

**These launch/browser steps were not executed in this session.** They use a separate Compose project, development placeholders, loopback host ports and private named volumes. Existing PostgreSQL services and application volumes are not selected. Approved BO6 checkpoints must already be present as documented in `ml-service/ARTIFACTS.md`.

From the repository root in a dedicated PowerShell terminal:

```powershell
$env:APP_ENV = 'development'
$env:VTON_MODE = 'mock'
$env:POSTGRES_USER = 'dressme'
$env:POSTGRES_PASSWORD = 'local-development-only-change-me'
$env:POSTGRES_DB = 'dressme'
$env:DATABASE_URL = 'postgresql+psycopg://dressme:local-development-only-change-me@postgres:5432/dressme'
$env:REDIS_URL = 'redis://redis:6379/0'
$env:BACKEND_PORT = '127.0.0.1:18080'
$env:FRONTEND_PORT = '127.0.0.1:18081'
$env:FRONTEND_ORIGINS = 'http://127.0.0.1:18081'
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example config --quiet
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example run --build --rm backend alembic upgrade head
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example up --build -d
```

Open `http://127.0.0.1:18081`. Use synthetic test images/account data: sign in/register, upload/review/save a garment, open Try-On, explicitly consent to a person-photo upload, select both inputs, and submit the mock preview. The existing UI should poll queued/running to succeeded and display a contact sheet labelled `MOCK TRY-ON · NO IMAGE GENERATION` with mock metadata. A healthy backend or running container alone does not prove this sequence; require the actual displayed result and a second user's denied direct result access.

Useful operator checks:

```powershell
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example ps
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example logs --tail 80 tryon-dispatcher tryon-worker
# Normal shutdown retains the isolated demo volumes.
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example down
```

For a bounded worker delivery inside that isolated stack, stop its background worker, submit a job and wait for dispatch, then run:

```powershell
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example stop tryon-worker
docker compose -p dressme-bo7-mock-demo-20261008 --env-file .env.example run --rm tryon-worker python -m app.tryon.worker --burst --max-jobs 1
```

Burst mode exits if the queue is empty; its exit code alone cannot establish result completion. Read the owner-visible job state/result in the UI. For an already configured local Windows API, real loopback Redis, matching isolated DATABASE_URL/STORAGE_PATH and a separately running dispatcher, the analogous worker command from `backend/` is `.\.venv\Scripts\python.exe -m app.tryon.worker --simple-mock --burst --max-jobs 1`. This native option is development/test only, lacks per-job process isolation and remains unverified against a real broker.

## FASHN settings, remaining criteria and next action

The existing frozen FASHN package's `config/inference_defaults.json` supports preview 20 steps and balanced 30 steps, seed 42, guidance 1.5, one sample, segmentation-free mode and per-garment photo type. `fashn_infer.py` permits an explicit timestep override, but the vendored pipeline selects bfloat16 on supported CUDA hardware and float32 otherwise; it does not expose the selected strict FP16 profile. No 15-step/strict-FP16 profile was silently replaced, and no FASHN source/settings/artifacts were changed. The private archive/source exists; artifact restoration and actual CUDA/ONNX provider execution were not performed here.

| Completion criterion | Evidence / status |
|---|---|
| Preserve BO6/auth/private data and unrelated changes | No production auth/storage/schema/BO6/UI edits. Test auth limit is verified; report prefix and PDF hash are checked separately. |
| Useful missing adapter/integration work when infrastructure is blocked | **PASS (offline contracts):** profile guards, bounded/explicit mock worker launch, timestamp recovery, publication race suppression. |
| Labelled mock worker output and private owner retrieval | **PASS (direct worker/API tests only):** valid PNG, mock metadata, no-store/nosniff, unauthenticated 401 and another owner 404. |
| Browser submission → Redis/RQ → worker → result → UI | **BLOCKED / NOT VERIFIED:** Docker pipe denial and missing Redis runtime. No new browser result evidence. |
| Real FASHN generation on selected profile | **NOT ATTEMPTED:** mock runtime gate unmet and current Torch is CPU-only; profile support also remains unresolved. |
| Full recovery/persistence/ownership matrix on real services | **NOT VERIFIED:** broker outage, worker crash/restart, process-level timeout/cancellation, PostgreSQL concurrency/restart and result deletion races still need live acceptance. |

The smallest next action is restore ordinary Docker Desktop engine access for this user/session through the user's normal environment setup, then execute the isolated mock launch and browser/result path above. Require Gate A evidence before attempting one real FASHN generation. Overall BO7 and Gate A remain **INCOMPLETE**; real inference and Hybrid Avatar completion are not claimed.
