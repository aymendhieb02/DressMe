# Integration verification — 29 October 2026

## Exact local baseline and checks

Team baseline SHA `6db709ade062bad5c7ca7be7ee85d4b88c2fdfee` was cloned into an initially empty target directory. A local venv was created with `python -m venv --system-site-packages .venv`; `python -m pip install -r requirements.txt` installed the missing `open_clip_torch` and Transformers dependencies. Before integration, TestClient returned `root 200`, `catalog 200`, `examples 200`, `score 200`. Guessed paths `/api/search/status` and `/api/wardrobe` returned 404; the supported search and wardrobe endpoints are under `/api/search/{similar,shops}` and `/api/wardrobe/{sample,complete}`. One baseline `/api/complete` request began a first-use public model download and was stopped before a result; no baseline result is claimed for it.

After integration:

| Check | Result |
|---|---|
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

## Publication safeguard

Publication is limited to `refs/heads/integration_bo6_bo7` using an explicit refspec. The preservation manifest and staged-file audit exclude private state and model weights. This migration remains incomplete while avatar/provider and real VTON work are unresolved.
