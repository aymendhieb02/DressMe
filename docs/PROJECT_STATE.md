# Project state — 31 October 2026

- Branch: `integration_bo6_bo7`, worktree base commit `e531446bfc3f69d1e441734058c31f428b4cb30c`; delivery commit is in the branch history.
- Source protection: work occurred in `D:\5eme\DressMe\projet_integration`. The original source checkout was not edited by this task; it had unrelated modified and untracked files when inspected, and they were left untouched.
- Architecture: original FastAPI application with vanilla HTML/CSS/JavaScript and the five public sections; private Studio API mounted at `/studio-api`; independent FastAPI BO6 inference service; SQLAlchemy/Alembic, PostgreSQL, private storage abstraction, optional Redis/RQ.
- BO6: valid exported `E03_efficientnet_b0` bundle, taxonomy `dressme-v0.2`; full manifest and 17/17 bundle self-test pass. Real browser inference and save/edit/reload pass using the local service. Bundle artifacts were not changed.
- Studio frontend: modular files under `static/studio/` for shared state/API, authentication, uploads, wardrobe/review, avatar and try-on/history. Authentication-first navigation, review suggestions, confirmed descriptions, detail editing, upload feedback and mobile layouts passed the current browser journey.
- Authentication/recovery: password-code reset is implemented with generic public responses, protected verifier, expiry/attempt/cooldown/rate controls, superseding codes, atomic single-use claim, password policy and session revocation. Local captured-email browser journey passed. Real SMTP delivery is not verified.
- Team setup: independent Python 3.11 app and BO6 dependency locks came from successful clean installs. Windows setup/start/check/stop and checksum-safe restore scripts are documented in `TEAM_SETUP.md`; no model weights, private storage, database, credentials or SMTP values are committed.
- Original team features: all five public sections remain navigable. External weather, shopping and pretrained CLIP/SigLIP model-assisted calls were not fully revalidated. Those inherited routes can download upstream weights on first use; no repository-controlled checksums or restoration flow exists for them.
- Existing account: non-destructive sign-in/session verification was not run because `DRESSME_TEST_PASSWORD` was unset. The account and its records/sessions were untouched.
- Redis/RQ: unavailable (`redis_unavailable`); no live queued MOCK job ran. Controlled browser testing confirmed disabled UI when unavailable and enabled UI with a controlled ready response; no job was submitted in that test.
- Avatar/real VTON: Avaturn provider session/export unverified; PNG avatar rendering not implemented. Real VTON adapter is unavailable; only MOCK labeling and UI are present.
- Local verification data: isolated acceptance SQLite database, private temporary storage, captured test email and screenshots live under `%LOCALAPPDATA%\Temp\DressMeStudioAcceptance_20261031_01`; the server was stopped after verification. Existing user demo services on ports 8002 and 18022 were not stopped or reconfigured.
- Deployment: no Docker/Compose deployment was attempted in this work. No database reset, model replacement, source checkout edit or merge was performed.

The preservation manifest was regenerated against historical baseline `6db709ade062bad5c7ca7be7ee85d4b88c2fdfee`: 1,181 of 1,186 original tracked files are unchanged; five tracked changes and 153 later additions are recorded.

See `docs/INTEGRATION_VERIFICATION.md` for exact commands, test counts, screenshots and blockers.
