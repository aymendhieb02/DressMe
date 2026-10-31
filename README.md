# DressMe

This integration branch preserves the five original public team features and adds an authentication-first private Studio for BO6 garments and the currently available BO7 avatar/try-on workflows. The application remains FastAPI with a plain HTML/CSS/JavaScript frontend. BO6 inference runs as a separate FastAPI service; PostgreSQL/SQLAlchemy/Alembic and private local storage back Studio records. Redis/RQ is optional and produces MOCK jobs only.

## Set up a teammate checkout

Follow [TEAM_SETUP.md](TEAM_SETUP.md) for Python 3.11 Windows setup, independent pinned environments, local credentials and PostgreSQL configuration, checksum-verified BO6 weight restoration, explicit migrations, service startup/health/shutdown commands, optional SMTP/Avaturn/Redis setup, and current capability limits.

```powershell
.\scripts\dev\setup.ps1 -Developer -IncludeBo6
```

Setup does not modify an existing `.env`, create a database, run migrations, access the original source checkout or download model weights. The runtime and developer dependency locks are separate for the application and BO6 service.

## Current capability notes

- BO6 performs real CPU classification and description with the existing checksum-verified exported bundle; the model weights are not tracked in Git.
- The five public sections remain in the same application.
- Studio provides private auth, upload/review/describe/save/edit, wardrobe export, and account recovery through local email capture or configured SMTP.
- The avatar creator depends on an approved Avaturn origin. PNG rendering is not implemented.
- Try-on is labeled MOCK. Redis/RQ must be available for queue completion. A real BO7 VTON adapter is unavailable.
- The legacy public Style Engine and Find Similar flows can download upstream CLIP/SigLIP weights on their first model-assisted request; details and the current limitation are documented in [TEAM_SETUP.md](TEAM_SETUP.md).

## Verification records

- [Integration verification and outstanding blockers](docs/INTEGRATION_VERIFICATION.md)
- [Project state](docs/PROJECT_STATE.md)
- [BO6/BO7 migration map](docs/BO6_BO7_MIGRATION_MAP.md)
