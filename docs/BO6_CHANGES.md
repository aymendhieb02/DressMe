# BO6 integration: change list

Push checklist for Khaled. Every file changed or created by the BO6 work, and why. Plan: `docs/BO6_INTEGRATION_PLAN.md`.

## Files in the repo

| File | Change | Why | Step |
|---|---|---|---|
| `.gitignore` | Added `*.safetensors`, `*.npz`, `bo6_g2l/`, `bo6_service/bundle_g2l/`, `.venv-bo6-g2l/` | Keeps weights and the bundle out of the push. `bo6_service/bundle/parity_reference.npz` was already tracked and stays tracked | 0 |
| `docs/BO6_INTEGRATION_PLAN.md` | New | The plan | Planning |
| `docs/BO6_CHANGES.md` | New | This checklist | 0 |
| `bo6_service/app/g2l_runtime.py` | New | Serves the G2L bundle behind the existing `/analyze` and `/describe` contract; normalises output; never returns the embedding | 3 |
| `bo6_service/app/main.py` | Picks the runtime from the bundle folder; `/describe` asks the runtime whether it accepts the fields | G2L upgrade, with `bundle/` as rollback | 3 |
| `bo6_service/app/model_runtime.py` | Added `accepts`; `describe` ignores fields the legacy bundle does not know | Keeps the old runtime working as rollback with the widened schema | 3 |
| `bo6_service/app/schemas.py` | Added values only: 9 categories, 3 colours, `three_quarter`; new optional `material`, `season` | G2L vocabulary | 3 |
| `bo6_service/requirements-g2l.in` | New | Pins for `.venv-bo6-g2l` (CPU torch, transformers) | 2 |
| `bo6_service/tests/test_g2l_runtime.py` | New | Normaliser and G2L runtime tests; bundle tests skip when the bundle is absent | 3 |
| `scripts/dev/start.ps1` | Added `-G2L` switch; checksum check now uses the chosen bundle path. Teammate's `.runtime` edit kept | Start BO6 from `bundle_g2l` and `.venv-bo6-g2l` | 3 |
| `scripts/dev/stop.ps1` | Recognises a BO6 service started from `.venv-bo6-g2l`. Teammate's edits kept | Otherwise `stop.ps1` would refuse to stop it | 3 |
| `app/garments/taxonomy.py` | New | Category to `super_category` / `outfit_cat` map and `w_` item codes | 4 |
| `app/garments/schemas.py` | Added values only (9 categories, 3 colours, `three_quarter`); new `material`, `season`; `GarmentView` gains 5 optional fields | G2L vocabulary and team fields | 4 |
| `app/garments/review.py` | `pants` added to bottoms; new `NO_SLEEVE_CATEGORIES` | No sleeves on bottoms, shoes, bags, accessories | 4 |
| `static/studio/wardrobe.js` | New category, colour and sleeve values; material select in review and edit forms; `BOTTOMS` became exported `NO_SLEEVES` | G2L vocabulary in the Studio | 4 |
| `static/studio.js` | Uses `NO_SLEEVES`; `material` in the dirty check | Same | 4 |
| `alembic/versions/0013_garment_wardrobe_profiles.py` | New, `down_revision = 0012_taste_reactions` | Side table for team fields. **Needs teammates' uncommitted 0012 pushed with it** | 5 |
| `app/models.py` | New `GarmentWardrobeProfile`; `Garment.profile` relationship; `LargeBinary` import. Teammate's `TasteReaction` kept | Same | 5 |
| `app/garments/router.py` | Profile created on save and updated on PATCH; material feeds the description; flush added in `delete_garment` | Step 6. The flush fixes a delete-order failure the new relationship exposed | 6 |
| `tests/test_garment_profiles.py` | New | Profile, season, replay, delete, ownership, vocabulary tests | 6 |
| `tests/test_migrations.py` | Added one migration test | `0013` up and down | 5 |
| `app/garments/eligibility.py` | `pants` maps to `bottoms`, same as `trousers` | `pants` is the new model's name for trousers; other new categories stay out of try-on | CP3 addition |
| `app/garments/router.py` | `_predicted_value`: a withheld category is compared with the top suggestion. New `POST /garments/uploads/manual` | Honest `was_corrected`; adding a garment while BO6 is down | CP3 addition, 7 |
| `static/studio/core.js` | Thrown errors carry the API `code` | Lets the upload fall back on `ml_unavailable` | 7 |
| `static/studio.js` | Upload falls back to the manual route when analysis is unavailable | Step 7 | 7 |
| `static/studio/wardrobe.js` | Requires a typed description on a manual upload | Step 7 | 7 |
| `wardrobe_owned.py` | New | Per-request overlay of a user's garments; lazy CLIP embedding; no global mutation | 8 |
| `wardrobe.py` | `owned_overlay`; `analyze`, `complete`, `outfits_route`, `me` use it when the flag is on; `build_looks(prefer=)`; `profile` skips owned ids | Step 8 | 8 |
| `scoring.py` | `score_outfits(outfits, E=None)` | Lets the overlay pass the stacked matrix; default unchanged | 8 |
| `app/config.py` | `bo6_enabled` from `BO6_ENABLED`, default off | Feature flag | 8 |
| `api.py` | `/api/studio-config` adds `bo6_enabled` only when on. Teammate's edits kept | Frontend menu entry; flag-off bytes unchanged | 8 |
| `tests/test_wardrobe_owned.py` | New | Real wardrobe routes on a fake catalog: flag, isolation, catalog-only recommendations, Men rule, embeddings | 8 |
| `tests/test_garment_profiles.py` | Added alias, `was_corrected` and manual upload tests | CP3 additions and step 7 | 7 |
| `static/index.html` | `#wardrobe` only: owned pieces on the shelves, "From your wardrobe" and "Starter" badges, "You own" row, Scan my real garment menu entry. Teammate's Taste edits kept | Step 9 | 9 |
| `static/studio/wardrobe.js` | After a scan started from `#wardrobe`, saving returns there | Step 9 | 9 |
| `wardrobe.py` | `build_looks`: at most 2/3 of looks (4 of 6) contain an owned piece, the rest are catalog looks | Keeps variety | CP4 addition |
| `scripts/dev/start.ps1` | Any BO6 problem is a warning; the app waits on `/health/live` and warns on `/health/ready` | App starts without BO6 | CP4 addition |
| `tests/test_wardrobe_owned.py` | Added look cap and fallback tests | Same | CP4 addition |
| `.env.example` | Added `BO6_ENABLED=0` | Documents the flag | 8 |
| `scripts/dev/setup.ps1` | New `-G2L` switch builds `.venv-bo6-g2l` | No manual venv setup | Pre-push |
| `static/**` | All `?v=integrated-13` URLs became `?v=bo6g2l1`, together so each module loads once | Browsers fetch the new files | Pre-push |

## Must not be pushed

| Path | Why | Protected by |
|---|---|---|
| `bo6_g2l/` | Bundle, reports and figures containing retailer images | `.gitignore` |
| `bo6_service/bundle_g2l/` | 351 MB of weights | `.gitignore` |
| `.venv-bo6-g2l/` | 886 MB virtualenv | `.venv-*/` and `.venv-bo6-g2l/` in `.gitignore` |
| `var/backup_20261104/` | Database backups, personal data | `var/` in `.gitignore` |

## Outside the repo (safety copies)

| Path | Contents |
|---|---|
| `../bo6_pre_change.patch` | `git diff` before any BO6 change. Restore with `git apply` |
| `../bo6_pre_change_untracked/` | The 8,202 untracked files, including teammates' work. Excludes `bo6_g2l/` |

## After pulling

Run these from the repository root, in PowerShell.

1. Build the environments, including the G2L one (CPU torch and transformers):
   ```powershell
   .\scripts\dev\setup.ps1 -Developer -IncludeBo6 -G2L
   ```
2. Put the unzipped bundle in `bo6_service\bundle_g2l\`, so that `bo6_service\bundle_g2l\clip_vision\model.safetensors` exists. The bundle is private and not in Git; get it from Khaled.
3. Apply the migrations (`0012` and `0013`):
   ```powershell
   .\.venv-app\Scripts\python.exe -m alembic upgrade head
   ```
4. Turn the feature on, by adding `BO6_ENABLED=1` to `.env` or for one session:
   ```powershell
   $env:BO6_ENABLED = '1'
   ```
5. Start, then open `http://localhost:8002/app#wardrobe`:
   ```powershell
   .\scripts\dev\start.ps1 -AppPort 8002 -Bo6Port 18023 -G2L
   ```

Without the bundle, leave out `-G2L` to use the old model. `$env:DRESSME_LLM = 'off'` skips the Qwen load on machines with little memory.

## Push notes

- Push everything in the table above, plus teammates' Taste work. `0013` depends on their untracked `alembic/versions/0012_taste_reactions.py`, so it must go in the same push.
- `git status` must not list `bo6_g2l/`, `bo6_service/bundle_g2l/`, `.venv-bo6-g2l/` or `var/`.
- Tests need the origins they send: set `FRONTEND_ORIGINS=http://localhost:8001,http://localhost:8002` first.

## Local database state

`var/dressme.sqlite` is migrated to `0013`. Backup from before the migration: `var/backup_20261104/`. Each teammate must run `alembic upgrade head` after pulling.

## Follow-ups (out of scope)

- Q7: owned garments in Verdict, My Outfit, Daily Edit and BO3.
- Q9: which new categories try-on accepts. Only `pants` was added, as an alias of `trousers`; `blouse`, `cardigan`, `jumpsuit` and the other new categories are not try-on eligible.
- Q10: CSRF on `/api/wardrobe/*` writes.
