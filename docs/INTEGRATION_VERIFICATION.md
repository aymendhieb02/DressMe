# Integration verification

## Responsive UI continuation — 31 October 2026

This follow-up was performed only in `D:\5eme\DressMe\projet_integration`, branch `integration_bo6_bo7`, from base commit `604a9b6c8f27de781f963b2dcaa5a8f740da7d84`. The worktree was clean at the start. The separate source checkout `D:\5eme\DressMe\Projet_DressMe` contained unrelated modified and untracked files; it was not edited. The exported model bundle was not modified.

### Findings and changes

- Baseline browser screenshots showed the public navigation continuing horizontally at phone widths, with the `My Studio` button ending beyond the viewport. Before changes, the existing probe measured a 390px viewport with `documentElement.scrollWidth=541`, menu bounds `x=42..381.5`, and clipped Studio navigation; the 768px public page measured 859px wide. Studio page-level `overflow-x:hidden` had masked some document overflow.
- Added a compact mobile `Menu` disclosure. Its three groups open one at a time, each group and route has keyboard support, Escape closes a group then the global menu and returns focus, outside click closes the menu, and resize resets disclosure state. Desktop group hover/focus remains available. The rotated decorative wall is contained by a fixed background wrapper rather than by clipping the page.
- Added the five-page native Studio section disclosure for compact widths. Auth routes hide the repeated public hero and remove the nested `main` element. Password inputs and labels remain accessible at narrow widths.
- Add Garment now uses the available Studio content width: the upload and its single preview sit in one column beside suggestions and confirmation when that content column is at least 760px; narrower content stacks. The review no longer repeats the image already visible in the upload panel. Suggestions, confirmed fields, description, save flow, and BO6 inference behavior remain unchanged.

### Verification

`node scripts/browser_check.cjs` passed with **30 PASS checkpoints**, including the public sections, all ten public/Studio destinations, menu group touch targets and hit tests, keyboard focus/Escape, outside click, resize transitions, login/registration/recovery layouts, five Studio pages, real BO6 analyze → review → generated description → save → edit → reload, and disposable-account cleanup. Every affected view was browser-emulated at 320, 360, 390, 768, 1024 and 1440 CSS pixels, plus a 568×320 short landscape viewport. The browser audit checked document/body scroll width, horizontal control bounds, clipped controls, and center hit tests. Menu and compact Studio targets have CSS minimum heights of 44px.

The BO6 browser journey used the tracked catalog fixture `data/img/P01133864.jpg` and the healthy real service at `127.0.0.1:18022` (`E03_efficientnet_b0`). The application test server used port 8013, the dedicated migrated SQLite file `C:\Users\Msi\AppData\Local\Temp\DressMeResponsiveAcceptance_20261031_01\acceptance.sqlite`, private storage/mail directories under the same temporary root, and no user demo database. The disposable account and its owned records were deleted by the browser check. Both test service sessions were stopped after verification; the earlier bind attempt on 18022 failed because the already-running healthy service owned that port, and it was reused read-only for inference.

The browser was Chromium emulation, not physical-device testing. The UI is served as static HTML/CSS/JavaScript; the repository has no frontend `package.json`, Vite, or separate production build command. No production frontend bundle was generated. Full-page and viewport captures remain outside Git at `C:\Users\Msi\AppData\Local\Temp\DressMeResponsiveAcceptance_20261031_01\screenshots\responsive-after\`, including `public-menu-open-390-viewport.png`, `auth-login-390-full.png`, `bo6-review-390-full.png`, `studio-bo6-wardrobe-390-full.png`, and the avatar/try-on/history captures. These show disposable account data only.

Exact browser command and configuration:

```powershell
$env:DRESSME_BASE_URL='http://127.0.0.1:8013'
$env:DRESSME_PLAYWRIGHT_PATH='C:\Users\Msi\AppData\Local\Temp\dressme-browser-tools\node_modules\playwright'
$env:DRESSME_BROWSER_EXECUTABLE='C:\Users\Msi\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe'
$env:DRESSME_SCREENSHOT_DIR='C:\Users\Msi\AppData\Local\Temp\DressMeResponsiveAcceptance_20261031_01\screenshots'
$env:DRESSME_CAPTURE_PATH='C:\Users\Msi\AppData\Local\Temp\DressMeResponsiveAcceptance_20261031_01\mail'
node scripts/browser_check.cjs
```

Additional checks: browser page-error list empty; `node --check scripts/browser_check.cjs` passed; inline script parsing passed; `git diff --check` passed; `git diff --quiet HEAD -- bo6_service/bundle` passed. The complete application and BO6 Python suites were not rerun because no backend or ML code changed.

## Previous continuation — 31 October 2026 (before responsive follow-up)

Work was performed only in `D:\5eme\DressMe\projet_integration`, on branch `integration_bo6_bo7`, from worktree base `e531446bfc3f69d1e441734058c31f428b4cb30c`. New checks ran against this task worktree before its delivery commit; the delivery SHA is available in Git history and the final task report. The source checkout `D:\5eme\DressMe\Projet_DressMe` was not edited by this task. It had unrelated modified and untracked files when inspected; they were left untouched.

### Current results

| Area | Result and evidence |
|---|---|
| Application suite | PASS: `87 passed in 16.92s` using the generated developer lock in a new `python -m venv` environment with system site packages disabled. Command: `& $appLockPython -m pytest tests -q`. |
| BO6 suite | PASS: `16 passed in 5.10s`; one Starlette deprecation warning recommends `httpx2`. Command: `Push-Location .\bo6_service; & $bo6LockPython -m pytest tests -q; Pop-Location`. |
| Dependency locks | PASS: clean installs of `requirements-dev.lock` and `bo6_service/requirements-dev.lock`; both returned `No broken requirements found.` The runtime locks are separate, and `requirements.txt` points to the app lock. Python 3.11.9 / Windows x64 was tested. |
| BO6 bundle | PASS: clean BO6 environment verified the complete checksum manifest, then `bundle/selftest.py` returned `passed=true`, `n_checks=17`. `restore-model-bundle.ps1` was exercised against the already-valid target bundle; it reported existing weights unchanged and repeated all 17 self-tests. `git diff --quiet HEAD -- bo6_service/bundle` passed. No model artifacts were modified. |
| Browser journey | PASS, 13 checkpoints: original five public sections; invalid-login feedback and keyboard registration focus; auth-first route and return; deep links/reload/sidebar/Back/unique IDs; upload format-error announcement, drag/drop preview and keyboard file removal; detail Cancel focus return; real BO6 image analyze → explicit category/attribute confirmation → generated description → save → edit → reload; 360/390/768/1440 CSS-pixel layouts; live unavailable-worker/provider messages; controlled available-worker UI; revoked-session sign-in message; captured-email recovery, old-password rejection and other-session revocation; disposable account/records removed. No browser page errors. |
| BO6 inference mode | PASS: browser upload used the running local BO6 HTTP service on `127.0.0.1:18022` and returned real bundle suggestions/description. The application test API used a temporary SQLite database on `127.0.0.1:8012`; it did not touch the persistent demo database. |
| Password recovery | PASS implementation and local capture: generic known/unknown request response, hashed verifier, expiry, cooldown, attempt limit, superseding code, atomic single use, session revocation and subsequent sign-in are covered by backend tests and the captured-email browser journey. Real SMTP delivery was not attempted. |
| Existing user account | NOT RUN: a presence-only check returned `DRESSME_TEST_PASSWORD is unset`. No attempt was made to sign into `aymen.dhieb@esprit.tn`, and no account data or sessions were changed. |
| Redis/RQ | BLOCKED live: `/health/try-on` reported `redis_unavailable`; no queue job was submitted. Controlled browser routes exercised the enabled UI only; the script explicitly confirms no job was sent. |
| Avaturn and real VTON | NOT VERIFIED: Avaturn was unconfigured in the isolated browser origin; real provider initialization/export and PNG rendering remain unavailable/unverified. No real VTON adapter exists; MOCK status remains explicit. |
| Browser evidence | PASS, browser emulation only. Before screenshots are the committed baseline files listed below. After screenshots were captured outside Git under `C:\Users\Msi\AppData\Local\Temp\DressMeStudioAcceptance_20261031_01\screenshots\` (`team-ootd-desktop.png`, `team-ootd-mobile.png`, `studio-login-desktop.png`, `studio-login-mobile.png`, `bo6-review-desktop.png`, `bo6-wardrobe-mobile.png`). No physical devices or assistive-technology pass is claimed. |
| Windows scripts | PASS syntax parsing for `setup.ps1`, `start.ps1`, `check.ps1`, `stop.ps1`, and `restore-model-bundle.ps1`. The restore script was run against an already-valid bundle. `start.ps1`/`check.ps1`/`stop.ps1` were not used to manage the user's live demo processes. |
| Preservation manifest | PASS: regenerated against baseline `6db709ade062bad5c7ca7be7ee85d4b88c2fdfee`; 1,186 original tracked files counted, 1,181 unchanged, five intentional tracked-file changes, and 153 files added since that baseline. The ignored BO6 `.pt` weights were not staged or altered. |

The seven named recovery regressions in `tests/test_password_recovery.py` passed as part of the 87-test application suite: `test_password_recovery_is_generic_single_use_revokes_sessions_and_requires_sign_in`, `test_recovery_cooldown_expiry_attempt_limit_and_replacement`, `test_invalid_code_attempts_are_limited_and_unknown_account_verification_is_generic`, `test_recovery_code_expiry_is_enforced`, `test_atomic_recovery_claim_allows_only_one_concurrent_consumer`, `test_login_accepts_legacy_password_shorter_than_new_account_policy`, and `test_password_recovery_requires_frontend_origin`.

### Commands and outcomes

The lock files were generated from actual successful clean Python 3.11 installs and `pip freeze`; no versions or hashes were hand-invented. A `pip-tools compile --generate-hashes` attempt spent over 2.5 minutes resolving the large PyTorch/index graph without producing a lock and was manually interrupted. The checked-in locks pin the successfully resolved package versions, but do not claim artifact hashes.

Clean locked environments were created under `%TEMP%\dressme-clean-install-20261031`:

```powershell
$cleanRoot = Join-Path $env:TEMP 'dressme-clean-install-20261031'
python -m venv (Join-Path $cleanRoot 'app-lock-env')
& (Join-Path $cleanRoot 'app-lock-env\Scripts\python.exe') -m pip install -r requirements-dev.lock
& (Join-Path $cleanRoot 'app-lock-env\Scripts\python.exe') -m pip check
& (Join-Path $cleanRoot 'app-lock-env\Scripts\python.exe') -m pytest tests -q

python -m venv (Join-Path $cleanRoot 'bo6-lock-env')
& (Join-Path $cleanRoot 'bo6-lock-env\Scripts\python.exe') -m pip install -r bo6_service/requirements-dev.lock
& (Join-Path $cleanRoot 'bo6-lock-env\Scripts\python.exe') -m pip check
Push-Location .\bo6_service
& (Join-Path $cleanRoot 'bo6-lock-env\Scripts\python.exe') -m pytest tests -q
Pop-Location
```

Both lock installs printed `Successfully installed`; both `pip check` runs printed `No broken requirements found.` The test commands returned the counts in the results table. No system-site packages, user model cache or original checkout were used by these environments.

The browser run used this isolated command/configuration; the recovery pepper was generated privately in the server process and was not logged:

```powershell
$env:DRESSME_BASE_URL = 'http://127.0.0.1:8012'
$env:DRESSME_PLAYWRIGHT_PATH = Join-Path $env:TEMP 'dressme-browser-tools\node_modules\playwright'
$env:DRESSME_BROWSER_EXECUTABLE = 'C:\Users\Msi\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe'
$env:DRESSME_SCREENSHOT_DIR = 'C:\Users\Msi\AppData\Local\Temp\DressMeStudioAcceptance_20261031_01\screenshots'
$env:DRESSME_CAPTURE_PATH = 'C:\Users\Msi\AppData\Local\Temp\DressMeStudioAcceptance_20261031_01\mail'
node scripts/browser_check.cjs
```

Uvicorn used the existing isolated SQLite database under that temporary root, a private temporary file directory, the real BO6 service URL `http://127.0.0.1:18022`, and frontend origin `http://127.0.0.1:8012`. Its Alembic state was `0009_password_recovery (head)`. The isolated app process was stopped after browser verification; the user's pre-existing processes on ports 8002/18022 were not stopped or reconfigured.

The first full browser run exposed `active is not defined` in the try-on module. The module import was fixed; a focused disposable-account diagnostic then showed `Submission is disabled because the worker is unavailable (redis_unavailable)` and no page errors. The final accessibility checks also exposed that invalid credentials were passed through the session-expiry handler and labelled as an expired session. The shared request helper now reserves that redirect for authenticated requests; the browser test verifies accurate invalid-credential feedback and the separate session-expiry path after a real password-reset revocation. The complete browser journey was rerun afterward and passed.

### Remaining blockers and limitations

- Live Redis/RQ dispatch, worker completion, result ownership under real queued work, cancellation/deletion races and persistence after service/container recreation remain unverified because Redis was unavailable. This does not change the separate browser UI PASS for both unavailable and controlled-available states.
- The authorized existing-account sign-in/session check is pending the user's private `DRESSME_TEST_PASSWORD` variable. Do not reset this account, revoke its sessions or remove its records.
- SMTP real delivery, Avaturn provider acceptance/export, saved-avatar viewer with a real private GLB, physical-device behavior and screen-reader behavior were not verified.
- The inherited public CLIP/SigLIP endpoints lazy-download third-party weights on first model-assisted use. Their weight versions/checksums and explicit offline restoration workflow are not owned by this repository; `TEAM_SETUP.md` calls out this behavior. BO6 itself uses only its separate checksum-verified exported bundle.

Before screenshots from the previous integration run are committed under `docs/integration-screenshots/`, including `bo6-review-desktop.png`, `bo6-wardrobe-mobile.png`, `team-ootd-desktop.png` and `team-ootd-mobile.png`. Current screenshots stay outside Git under the temporary path above.

## Historical verification — 29 October 2026

## Exact local baseline and checks

Latest UI follow-up (31 October 2026): browser coverage clicks actual BO6 category and attribute suggestions and verifies exclusive category candidates, selected-chip state, matching-field updates, manual dropdown synchronization, and ineligible sleeve behavior for bottom categories. Suggestions remain unselected until clicked. Generated descriptions stay visible and are marked stale after confirmed-value changes; edits are preserved and regeneration clears the stale state. The real BO6 browser journey passed with a disposable account. Screenshots from reruns remain in the system temporary directory.

Team baseline SHA `6db709ade062bad5c7ca7be7ee85d4b88c2fdfee` was cloned into an initially empty target directory. A local venv was created with `python -m venv --system-site-packages .venv`; `python -m pip install -r requirements.txt` installed the missing `open_clip_torch` and Transformers dependencies. Before integration, TestClient returned `root 200`, `catalog 200`, `examples 200`, `score 200`. Guessed paths `/api/search/status` and `/api/wardrobe` returned 404; the supported search and wardrobe endpoints are under `/api/search/{similar,shops}` and `/api/wardrobe/{sample,complete}`. One baseline `/api/complete` request began a first-use public model download and was stopped before a result; no baseline result is claimed for it.

After integration:

| Check | Result |
|---|---|
| `python -m pytest tests -q` after lifecycle/config ordering repair | PASS, 79 passed in 22.35 s. Added outer-app lifespan, direct Studio lifespan, and disposable expired-upload/deferred-file cleanup checks. |
| Combined `uvicorn api:app` lifespan | PASS: outer lifespan enters Studio once; cleanup task is named, canceled and awaited; cleanup pass uses test-controlled functions without sleeping 30 seconds or touching private data. |
| Configuration import order | `load_dotenv(override=False)` now runs before combined app imports and before `app.config` constructs settings. Clean subprocess precedence coverage remains pending. |
| `bo6_service/bundle/selftest.py` with restored local `.pt` files | PASS, `passed=true`, `n_checks=17`. |
| `python -m alembic upgrade head` against dedicated database on port 55461 | PASS, revisions `0001` through `0008_private_avatar_renders`. |
| `GET http://127.0.0.1:18022/health` | 200, `E03_efficientnet_b0`, `dressme-v0.2`. |
| `GET http://127.0.0.1:8002/`, `/api/catalog`, `/studio-api/health/live` | All 200. |
| Original `/api/wardrobe/sample` and `/api/wardrobe/complete` | Sample returned 11 items; complete with six sampled IDs and `n=1` returned 200. |
| `GET http://127.0.0.1:8002/studio-api/health/ready` | 200, `database=true`, `bo6_service=true`, `inference_mode=bo6_real`, `vton_mode=mock`, `real_vton_ready=false`. |
| `GET /studio-api/health/try-on` | `status=unavailable`, broker/dispatcher/worker false, `reason=redis_unavailable`. Docker Linux pipe was absent; no Redis was started. |
| `node --check static/studio.js` | PASS. |
| `python -m pytest tests -q` from `bo6_service/` | PASS, 16 passed in 4.67 s on final run. |
| `python scripts/verify_integration.py` | PASS: real BO6 analysis of tracked catalog JPEG; two suggestions; confirmed trousers description; save/list/private image/edit/delete; unsupported text 415 and 10 MB overflow 413; second account's garment/image GET, PATCH and DELETE returned 404; owned CSV parsed as UTF-8 BOM with one row, second account CSV zero rows, no private key or database URL; disposable accounts deleted. |
| `python scripts/verify_restart.py prepare`, application restart, `python scripts/verify_restart.py finish` | PASS: saved garment, authentication session and private image still readable after restarting Uvicorn; disposable account deleted. PostgreSQL remained running. |
| `node scripts/browser_check.cjs` with installed Playwright/Chromium | PASS: all five original sections visible; new Studio deep link survives reload, sidebar route and browser Back work, IDs unique; real BO6 upload preview → explicit category confirmation → describe → save → edit → reload; desktop and 390px screenshots; no horizontal page scroll or clipped Studio navigation links at 360/390/768/1440px; BO7 mock and provider limits shown; vendored Avaturn SDK and 3D viewer modules load; account deleted. |
| Copied backend suite with source backend venv | PASS: 75 passed, 33 warnings. Command: `& 'D:\5eme\DressMe\Projet_DressMe\backend\.venv\Scripts\python.exe' -m pytest tests -q`. It reads target test/code files; no source tracked files changed. |
| Copied backend suite plus exact public-config regression with combined target venv | PASS, 76 passed in 12.61 s on final run. The team's unpinned Transformers resolved to 5.21.1 and installed `httpx2`; initially three cookie override tests failed because its TestClient persisted the active cookie instead of applying the per-request override. `tests/conftest.py` now isolates the cookie jar for those calls without changing assertions. The three focused tests and full suite passed after that fixture fix. |

The browser edit initially failed because a hidden input named `id` shadowed `HTMLFormElement.id`; the event handler now reads `getAttribute('id')`. A 390px viewport initially scrolled horizontally because the original decorative wall and new sidebar overflowed; the studio page scope clips page scrolling while leaving the original sections' styles untouched, and mobile navigation now wraps all links into visible rows. A navigation regression check then found that inactive Studio sections retained duplicate auth form IDs; rendering now clears their content. All fixes were rerun through the complete browser journey.

Source and target BO6 bundles were compared by SHA-256 after migration: 23 metadata/code files and both local `.pt` weights had zero differences. The read-only source service was temporarily started on port 18023 with Python bytecode writes disabled; the same tracked JPEG sent to source `/analyze` and target port 18022 `/analyze` returned 200/200 and identical JSON (top category `trousers`). The temporary source service was stopped. A direct config check rejected an Avaturn URL with a path and admitted only an exact HTTPS Avaturn origin; the live unconfigured route returned a null URL and zero export origins.

Representative screenshots: `integration-screenshots/team-ootd-desktop.png`, `team-ootd-mobile.png`, `bo6-review-desktop.png` and `bo6-wardrobe-mobile.png`. The BO6 fixture is a tracked team catalog JPEG, not a private person photo or model accuracy benchmark.

## Remaining verification and blockers

- No Redis executable or Docker Linux engine was available in this session. The mock RQ dispatcher/worker did not complete a job. Result ownership, cancellation/deletion races and container persistence were not exercised in the new stack.
- No real production VTON adapter/checkpoint was found in the source tree. `nvidia-smi` reported RTX 3050 Laptop, 4096 MiB; this alone does not establish FASHN runtime compatibility. No real generated image was claimed.
- The new avatar page can read/delete a saved avatar and submit a local Avaturn GLB export through the copied validated API. The Avaturn SDK creator/export path is ported with an explicit consent gate, exact origin/frame message check, origin-limited export download and 50 MB cap. A private 3D viewer is ported from the source dependency; it has not been exercised with a saved avatar in this browser. The provider account has not been tested on this local origin; automatic photo initialization and export are therefore unverified. PNG render capture/save remains to port.
- Original team recommendation, weather, image search and shop calls were not fully exercised because they can invoke first-use model downloads or external services. Their unchanged source and route/navigation baseline are preserved, but full API regression remains open.
- Browser checks used emulation, not physical mobile devices or assistive technology. Screenshots show disposable data only.
- Full Compose deployment, PostgreSQL cluster restart, integration import from old private data, and production HTTPS remain unverified. Application-service restart persistence passed. The separate local database is persistent; test account cleanup deleted only owned synthetic records.
- Reproducible clean-environment dependency resolution is still open: `requirements-studio.in` references a missing `requirements.lock`, app and BO6 service dependency pins conflict, and existing README setup uses `--system-site-packages`. No lockfile has been fabricated.
- Browser verification still assumes the live mock worker is unavailable; it needs separate deterministic UI cases for unavailable and available runtime before it is robust on a machine with Redis.

## Publication safeguard

Publication is limited to `refs/heads/integration_bo6_bo7` using an explicit refspec. The preservation manifest and staged-file audit exclude private state and model weights. This migration remains incomplete while avatar/provider and real VTON work are unresolved.
