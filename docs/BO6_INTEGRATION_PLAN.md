# BO6 integration plan: real garments in the DressMe wardrobe

Status: plan only, nothing implemented. Written 4 Nov 2026 against `integration_DressMe`, branch `main` at `ab0c9cd`, plus the uncommitted work described in 1.1. Line numbers refer to that working tree and will drift.

Bundle reviewed: `g2l-clip-lr-a85009f8`, read from `C:\Users\Msi\Downloads\BO6_G2L_everything.zip` (inner `dressme_bo6_g2l_bundle.zip`). It was read in memory only: not unzipped, and `selftest.py` was not run.

## Where the repo differs from the brief

These five points change the design. Points 1 and 2 need Khaled's sign-off before implementation.

| # | The brief says | What the repo shows | What this plan does |
|---|---|---|---|
| 1 | Save images to MinIO | There is no MinIO: no code, no config variable, nothing on port 9000, and nothing in `Projet_DressMe`'s compose file or `.env.example`. Private images go through `app/storage/local_disk.py`. | Use `LocalPrivateStorage`. Open question Q1. |
| 2 | New `user_garments` table, new `/bo6/predict` and `/wardrobe/items` | The Studio already does upload, BO6, correction and save per user (`app/garments/router.py`, `garments` table, `bo6_service/`). It has 0 rows and is not connected to `#wardrobe`. `POST /api/wardrobe/items` already exists and means "replace the whole wardrobe". | Reuse the Studio flow, add one side table, and connect it to `#wardrobe`. |
| 3 | "Complete my wardrobe" opens a random list | `/api/wardrobe/complete` is a scored greedy search, not random. The random part is the starter wardrobe: `random_wardrobe` gives each new account up to 14 catalog pieces. | Change the completion response, and mark owned pieces separately from starter pieces. |
| 4 | Bundle embedding is cosine 0.94 to the team's | 0.94 belongs to a candidate that was not selected (`laion/CLIP-ViT-B-32-laion2B-s34B-b79K`). The shipped model is `openai/clip-vit-base-patch32`, at cosine **0.02** to `emb_clip.npy`, so it is effectively unrelated. | Same rule as the brief, more strongly: never store it. Call `predict(..., return_embedding=False)`. |
| 5 | Option 1 (separate service) is a choice to make | `bo6_service/` already is that service, on 18022 / 18023. It cannot load the new bundle as written (see 1.10). | Add a G2L runtime to the existing service. |

---

## 1. Findings

### 1.1 Repo map

- **Backend:** Python 3.11.9, FastAPI. Root app is `api:app`; the Studio app (`app/main.py`) is mounted at `/studio-api`.
- **Frontend:** no build step for the app. `static/index.html` (about 1,630 lines of inline JS) plus ES modules in `static/studio/`. The landing page is built separately.
- **Running on 8002:** `.venv-app` running `uvicorn api:app --host localhost --port 8002 --workers 1`, with BO6 on 18023 using `.venv-bo6`. `scripts/dev/start.ps1` takes `-AppPort` and `-Bo6Port`, and its defaults are 8001 / 18022.
- **Tests:** `tests/`, `bo3/tests/`, `bo6_service/tests/`, run with pytest.
- **Uncommitted teammate work in this tree:** the Taste Studio feature (`reco.py`, `style.py`, `bubble.py`, `engine.py`, `alembic/versions/0012_taste_reactions.py`, and edits to `api.py`, `app/models.py`, `static/index.html`). It appeared during this session. The live database is already at `0012`, a migration that exists only as an untracked file. See step 0 and Q3.

### 1.2 Wardrobe page

`#wardrobe` is markup at `static/index.html:740-755`, with its JS around lines 1292-1556.

| UI action | Call | Notes |
|---|---|---|
| Load | `GET /api/wardrobe/me` | `{gender, items:[{i,c,d,k,photo?}]}`, seeds the starter wardrobe |
| Autosave | `POST /api/wardrobe/items` | Replaces all rows, `{items:[{i,photo}]}` |
| Stats | `POST /api/wardrobe/analyze` | `{items:[int],gender}` |
| Complete my wardrobe (`#wrun`) | `POST /api/wardrobe/complete` | `{items:[int],n,gender}` returns `{recs,before,after,looks,thr}` |
| + Add a piece, Take a photo | `POST /api/wardrobe/add_photo` | Multipart. Returns the **nearest catalog item** plus a base64 thumbnail |
| Browse the catalog | `GET /api/wardrobe/allowed` | Picks catalog ids |
| Sample wardrobe | `GET /api/wardrobe/sample` | |

Today's "add a photo" does not store the real garment. It stores a catalog lookalike's id with the user's thumbnail attached. The real add flow is the Studio page `#bo6-add` (`static/studio.js:122`, `static/studio/wardrobe.js`).

### 1.3 "Complete my wardrobe" logic

- **Path:** `wardrobe.py::complete` (line 1642) calls `clean`, then `run_completion` (667), which calls `pool` (407), `enum` (254) and `score_outfits` (329), and then `build_looks` (592).
- **Candidate selection:** `pool` takes the catalog items nearest the wardrobe's mean embedding, plus a few extras from an RNG seeded with `len(cur)`.
- **Data used:** `catalog.json`, `emb_clip.npy` (`a.EMB`), `emb_ft.npy` and `scorer.pt` (through `scoring.py`), `outfits.json` (`a.TEST`, for `auto_thr`), `catalog_gender.json`. `search_meta.json` is not used here; it belongs to `similar.py`.
- **Item identity:** the list **position** in `catalog.json` (0-652) is the id everywhere, not the `P01133864` code. `check`, `ok_item`, and `E[items]` in `scoring.py` all index arrays directly.
- **Trap 1:** the frontend pushes accepted recommendations into `WD.items` and saves them, so `wardrobe_items` mixes starter pieces, recommendations, catalog picks and photo lookalikes. **`owned` cannot be derived from `wardrobe_items`.**
- **Trap 2:** `GET /api/wardrobe/me` also feeds the Verdict and My Outfit pickers (`mineFetch`, `index.html:982`) and BO3 (`bo3.html:564`). `ootd.py:398` reads the table directly. `scoring._check` rejects ids outside the catalog with 400. **Non-catalog ids must not appear in `items`.**
- **Best merge point:** the three route handlers (`/analyze`, `/complete`, `/outfits`). Every helper already takes the catalog as a parameter `a`, so a per-request overlay can stand in for it (see section 5).

### 1.4 Users and auth

- Session cookies. `app/auth/dependencies.py` provides `session_context`, `current_user` and `current_user_csrf`.
- The middleware in `api.py` requires a session for `/api/*`, and enforces CSRF only for `/api/assistant/`, `/api/reco/`, `/api/style/`, `/api/bubble/`. `/api/wardrobe/*` writes have **no CSRF check**. `/studio-api` writes do.
- `wardrobe.py::current_ctx` returns `{uid, gender, user}`. `/analyze`, `/complete`, `/outfits` and `/add_photo` currently take no user dependency.
- Per-user tables already exist: `garments`, `pending_uploads`, `person_photos`, `taste_reactions`, `wardrobe_items`, `wardrobe_profile`.

### 1.5 SQLite

There are two separate files, with no foreign keys between them.

| File | Access | Tables (rows) |
|---|---|---|
| `var/dressme.sqlite` (`DATABASE_URL` variable; value not read) | SQLAlchemy + Alembic, at `0012_taste_reactions`, `PRAGMA foreign_keys=ON` (`app/database.py`) | `users` (1), `auth_sessions` (6), `garments` (0), `pending_uploads` (0), `person_photos` (0), `taste_reactions` (13), `storage_deletions` (0), avatar and try-on tables (0) |
| `var/wardrobe.db` (`DRESSME_WARDROBE_DB`) | Raw `sqlite3` in `wardrobe.py::with_db`, self-migrating | `wardrobe_profile` (1), `wardrobe_items` (16) |

```sql
wardrobe_items(user_id TEXT, item_id INTEGER, photo TEXT, pos INTEGER, PRIMARY KEY(user_id,item_id))
wardrobe_profile(user_id TEXT PRIMARY KEY, gender TEXT, updated_at TEXT, seeded INTEGER)
```

`garments` already holds `user_id`, `pending_upload_id`, `image_key`, `category`, `garment_photo_type`, `vton_eligibility`, `color`, `pattern`, `sleeve_length`, `description`, `description_is_manual`, `name`, `notes`, `prediction_snapshot`, `quality_snapshot`, `field_sources`, `was_corrected`, `model_version`, `taxonomy_version`, `description_version`, `description_provenance` and timestamps. The full definition is in `app/models.py`.

### 1.6 Image storage

No MinIO. `LocalPrivateStorage` writes flat keys matching `^[0-9a-f]{32}\.png$` under `STORAGE_PATH`. Images reach the browser through authenticated proxy routes such as `GET /studio-api/garments/{id}/image` (`private, no-store`). Ownership lives in the database row, not in the key. `app/uploads.py::normalize_image` normalises every upload to PNG.

### 1.7 Embeddings

- **Producer:** `bo1/score5itemready.ipynb`, cell 6 (load), cell 15 (`np.save`). Library `open_clip`, model `ViT-B-32`, pretrained `laion2b_s34b_b79k`, matching `data/config.json`.
- **Details:** `visual` tower with `preprocess` from `create_model_and_transforms`, on the original product images, in half precision.
- **`emb_ft` and `emb_clip`:** verified byte-identical, (653, 512), float32, L2-normalised, with `finetuned: false`. One vector per garment serves both.
- **Per-image call:** yes. `wardrobe.py::enc_image(a, raw)` (line 929) with `api.clip()` (line 69) already runs at request time in `add_photo`.
- **Not verified:** that `enc_image` reproduces `emb_clip.npy` closely. Its transform is hand-written, and `data/img` holds 320 px thumbnails rather than the originals. The 0.94 in the bundle report came from a different loader. Step 1 tests this.

### 1.8 Item schema mapping

| Team field | Source | BO6 field | Status |
|---|---|---|---|
| `k` / `code` | `catalog.json` | none | Generated: `w_<32 hex>` |
| `d` / `desc` | `catalog.json` | `desc` | Yes |
| `c` / `cat` | `catalog.json` | `outfit_cat` | Yes, but see below |
| `category`, `master_category` | `search_meta.json` | `category` | Yes |
| `super_category` | `search_meta.json` | `super_category` | Yes; values include `outerwear` |
| `attributes` | `search_meta.json` | `pattern`, `material` | Yes, via `to_team_record` |
| `final_color`, `predicted_color` | `search_meta.json` | `color` | Yes |
| `sleeve` | `search_meta.json` | `sleeve_length` | Yes |
| `season` | `search_meta.json` | `season` | Yes, rule-based |
| `mid_category` | `search_meta.json` | none | Bundle writes a constant `other` |
| `text_color` | `search_meta.json` | none | Bundle writes `null` |
| `g` (gender) | `catalog_gender.json` | none | Not needed: garment belongs to the account |
| outfit, style, colour-profile rows | `outfits.json`, `color_model` | none | Not filled |

`catalog.json` has 653 ids, all shaped `P` + digits, so `w_` cannot collide. Catalog categories are `top, bottom, outer, dress, shoes, bag, other, accessory`. BO6 maps its `accessory` class to `other`, and `enum` only builds outfits from `top, bottom, dress, shoes, outer, bag`, so an owned accessory is listed but never scored.

### 1.9 Python environment

- `.venv-app`: torch 2.8.0+cu126, transformers 4.57.3, open_clip 3.3.0. It already runs CLIP. No new dependency is needed for embeddings.
- `.venv-bo6`: torch 2.11.0+cpu, numpy 2.1.3. **`transformers` is not installed**, and the bundle needs it. Keep this out of `.venv-app`.

### 1.10 Why `bo6_service` cannot load the bundle today

| Existing expectation | New bundle |
|---|---|
| `GarmentDescriber(bundle=..., device="cpu")` (`model_runtime.py:19`) | Parameter is `bundle_dir` |
| `.clf.description`, `.clf.arch`, `.clf.taxonomy` (lines 22-24) | Absent; use `.cfg` and `render_description` |
| `/describe` renders without an image | `predict` needs an image; `render_description(fields)` returns `(sentence, desc)` |
| Output key `attributes` (read by `static/studio/wardrobe.js`) | Output key `attribute_scores`; the sleeve key is `sleeve` |
| Unknown fields are `"unknown"` | Unknown fields are `null` |
| 11 categories, `pattern: solid`, `sleeve: sleeveless` | 19 categories, `plain`, `none`, `three_quarter`, plus colours `gold`, `silver`, `multi` |
| `start.ps1` checks for `model_weights.pt`, `attribute_heads.pt` | `clip_vision/model.safetensors`, `heads.npz` |

`checksums.json` has the same format, and `quality_checks.py` is byte-identical, so `verify_bundle` and `check_image` carry over. Its `quality_config.json` is `quality-v0.2`.

---

## 2. Architecture choice

**Recommendation: Option 1, by extending the existing service.**

- **Inference:** `bo6_service` gains a G2L runtime, in its own venv `.venv-bo6-g2l`, with the bundle at `bo6_service/bundle_g2l/`. It keeps the existing `predict_lock` and loads once at startup. The app already calls it only through `app/ml/client.py`.
- **Why not Option 2:** `.venv-app` runs a 3B model on a 4 GB GPU, and its torch differs from the bundle's environment. Importing BO6 there couples their release to ours and removes the off switch.
- **Rollback:** point `MODEL_BUNDLE_DIR` back at `bundle/` and restart.
- **Team embeddings:** computed in the app process with the team's own `enc_image`, never in BO6.
- **Memory:** start G2L **in place of** the old model on 18023, not alongside it. Free RAM was 0.53 GB at the end of this investigation; the 8002 process holds about 15.5 GB.

---

## 3. API contract

All Studio routes need a session, and all writes need `X-CSRF-Token`. Limit: `MAX_UPLOAD_BYTES`, default 10 MB, JPEG / PNG / WEBP. Timeouts stay as configured in `app/config.py`: connect 2 s, read 30 s, write 10 s.

### Existing, unchanged path: `POST /studio-api/garments/analyze`

Multipart `image`, optional `Idempotency-Key`. The G2L runtime normalises output so app and UI keep one shape:

```json
{
  "id": "6f1c0a6e-...", "image_url": "/garments/uploads/6f1c.../image",
  "image_sha256": "...", "width": 900, "height": 1200,
  "quality": {"version": "quality-v0.2"},
  "prediction": {
    "category": "shirt", "score": 0.91, "category_confident": true, "needs_user_review": true,
    "suggestions": [{"category": "shirt", "score": 0.91}, {"category": "blouse", "score": 0.06}, {"category": "top", "score": 0.02}],
    "super_category": "top", "outfit_cat": "top",
    "description": "A white striped cotton shirt.", "desc": "white striped cotton shirt",
    "description_fields": {"category": "shirt", "color": "white", "pattern": "striped", "material": "cotton", "sleeve_length": "long", "season": "all"},
    "description_provenance": {"category": "classifier", "color": "image_model"},
    "attributes": {"color": {"value": "white", "eligible": true, "suggestions": [{"value": "white", "score": 0.93}]}},
    "model_version": "g2l-clip-lr-a85009f8", "taxonomy_version": "dressme-g2l-v1.0", "description_version": "tmpl-g2l-v1.0"
  },
  "expires_at": "2026-11-04T23:30:00+00:00"
}
```

Values are illustrative. Normalising means: `attribute_scores` to `attributes`, `sleeve` to `sleeve_length`, `null` to `"unknown"`, `plain` to `solid`, `none` to `sleeveless`. `embedding` is never present.

| Status | Code | Meaning | UI |
|---|---|---|---|
| 415 | `unsupported_media_type` | Wrong type | Choose another photo |
| 413 | `file_too_large` | Over the limit | Choose another photo |
| 422 | `unreadable_image`, `bo6_rejected_input` | Bad image | Choose another photo |
| 503 | `ml_unavailable` | BO6 down or timed out | Offer **Add manually** |

### New: `POST /studio-api/garments/uploads/manual`

Same input and CSRF rules, no BO6 call. This is needed because today a BO6 outage deletes the upload and returns 503, so **manual add does not currently work when BO6 is down**. A new route keeps `tests/test_garment_retries.py` valid.

```json
{"id": "...", "image_url": "/garments/uploads/.../image", "quality": {}, "prediction": {"status": "unavailable", "suggestions": []}, "expires_at": "..."}
```

`model_version` is `manual`. The UI then requires a typed description, which `save_garment` already accepts without calling BO6.

### Changed: `POST /studio-api/garments`

`SaveGarmentInput` gains optional `material` and `season`, and its enums widen as described in 4.3. Saving creates the profile row in the same transaction. Response stays `GarmentView` with `material`, `season`, `outfit_cat`, `item_code` added.

### Changed: wardrobe reads, only when the user has garments and the flag is on

`GET /api/wardrobe/me` adds a separate key. `items` stays catalog-only:

```json
{"gender": "women", "items": [{"i": 12, "c": "top", "d": "...", "k": "P01133864"}],
 "owned": [{"i": 1000007, "c": "top", "d": "white striped cotton shirt", "k": "w_3f9a...", "owned": true, "photo": "/studio-api/garments/3f9a.../image"}]}
```

`POST /api/wardrobe/complete` keeps its request body. Owned garments are loaded server-side from the session, never from client ids. The response adds:

```json
{"recs": [], "before": 4, "after": 9, "thr": 7.0,
 "looks": [{"items": [{"i": 1000007, "owned": true}], "score": 8.1, "new": [], "owned": [1000007]}],
 "owned_in_looks": [{"i": 1000007, "d": "...", "photo": "...", "looks": 3}]}
```

`/analyze` and `/outfits` follow the same rule. A user with no garments gets today's response byte for byte, with no new keys. `POST /api/wardrobe/items` is unchanged; ids it does not recognise are already dropped by `ok_item`.

---

## 4. Data model

### 4.1 Reuse, not a new garment table

| Brief's `user_garments` field | Lives in |
|---|---|
| `id`, `user_id`, `image_key`, `category`, `color`, `pattern`, `created_at` | `garments` (existing) |
| `desc`, `sleeve` | `garments.description`, `garments.sleeve_length` |
| `bo6_model_version`, `bo6_raw_json`, `user_corrected` | `garments.model_version`, `prediction_snapshot`, `was_corrected` |
| `super_category`, `outfit_cat`, `material`, `season`, embedding | New side table |

A side table keeps the migration purely additive: rollback is one `DROP TABLE`, and it avoids SQLite batch rebuilds of `garments`.

### 4.2 Migration `0013_garment_wardrobe_profiles`

`down_revision = "0012_taste_reactions"`, subject to Q3.

```sql
CREATE TABLE garment_wardrobe_profiles (
  seq              INTEGER PRIMARY KEY AUTOINCREMENT,
  garment_id       CHAR(32)    NOT NULL UNIQUE REFERENCES garments(id) ON DELETE CASCADE,
  user_id          CHAR(32)    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_code        VARCHAR(40) NOT NULL UNIQUE,
  super_category   VARCHAR(32),
  outfit_cat       VARCHAR(16) NOT NULL,
  material         VARCHAR(32),
  season           VARCHAR(16),
  clip_embedding   BLOB,
  embedding_model  VARCHAR(64),
  embedding_status VARCHAR(16) NOT NULL DEFAULT 'pending',
  created_at       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT ck_gwp_cat    CHECK (outfit_cat IN ('top','bottom','outer','dress','shoes','bag','other')),
  CONSTRAINT ck_gwp_status CHECK (embedding_status IN ('pending','ready','failed'))
);
CREATE INDEX ix_gwp_user_cat ON garment_wardrobe_profiles (user_id, outfit_cat);
```

Down-migration: `DROP INDEX ix_gwp_user_cat; DROP TABLE garment_wardrobe_profiles;`

Use `sqlite_autoincrement=True` in Alembic so `seq` is never reused after a delete. `delete_garment` needs no change: `ON DELETE CASCADE` applies because the engine sets `foreign_keys=ON`.

**IDs:**
- `item_code` = `w_` + 32 hex. Stands in for `k`.
- Public integer id = `1_000_000 + seq`. The frontend and scorer need integers, the catalog ends at 652, and the offset leaves room for catalog growth.
- Inside a request, public ids map to dense array positions; see section 5.

**Images:** `LocalPrivateStorage` keeps flat keys. The brief's `users/{user_id}/garments/{item_id}.jpg` would need a new storage class, and the existing `garments.image_key` plus `user_id` already scope access.

### 4.3 Vocabulary changes

Add values and remove none, so old rows and the 8001 checkout stay valid.

| Field | Add |
|---|---|
| `category` | `blouse, cardigan, vest, pants, jumpsuit, coat, shoes, bag, accessory` (keep `trousers`) |
| `color` | `gold, silver, multi` |
| `sleeve_length` | `three_quarter` |
| new `material` | `cashmere, cotton, denim, leather, linen, silk, suede, synthetic, wool` |
| new `season` | Values from the bundle's `season_rule` (confirm in step 3) |

Touches `app/garments/schemas.py`, `bo6_service/app/schemas.py`, `static/studio/wardrobe.js` (lists and `BOTTOMS`), `app/garments/review.py` (`BOTTOM_CATEGORIES` gains `pants`), and `app/garments/eligibility.py`. A new `app/garments/taxonomy.py` holds the category to `super_category` and `outfit_cat` map, because the corrected category decides these, not the prediction.

---

## 5. "Complete my wardrobe" change

### Backend: per-request overlay

New file `wardrobe_owned.py`. `OwnedCatalog` wraps `A()`:

- `EMB` = catalog rows stacked with this user's vectors; `CAT` and `BYCAT` extended; `it(i)` returns owned dicts.
- Dense positions are `len(catalog) + k`, mapped to and from public ids at the route boundary.
- `.scoring.score_outfits` passes the stacked matrix.
- Nothing global is mutated, so one user's garments cannot reach another request.

| File | Change |
|---|---|
| `scoring.py::score_outfits` | Add optional `E=None`, default unchanged |
| `wardrobe.py::analyze`, `complete`, `outfits_route` | Add `ctx=Depends(current_ctx)`. Run `clean` on the catalog as now, then append owned positions |
| `wardrobe.py::build_looks` | Add `prefer=()`, same pattern as the existing `need_bag` filter: keep outfits with an owned piece, falling back to all |
| `wardrobe.py::profile` | Pass catalog items only, otherwise `style_matrix()[W]` raises and the existing `except` silently drops style |
| `wardrobe.py::me` | Add `owned` when non-empty |

- **Recommendations stay catalog-only:** `pool` draws from the base `BYCAT` lists, and `ok_item` still filters them. Owned pieces influence the wardrobe centre and the `0.92` near-duplicate filter.
- **Eligibility:** owned pieces with `embedding_status != 'ready'` or category `other` are listed but not scored. In a Men wardrobe, an owned `dress` is excluded from scoring to match `ok_item` (Q6).
- **Shown:** all owned pieces on the shelves, the existing 6 looks, and a "You own" row of up to 8 pieces used in those looks, most used first.

### Frontend (`static/index.html`)

- Add `WD.owned`, set in `wdLoad`. Never push owned pieces into `WD.items`, so `wdPayload`, `mineFetch` and BO3 stay untouched.
- `wdPut`: render owned pieces with a `.gi.owned` border and a "From your wardrobe" badge, without the × remove button. Deleting stays in My Wardrobe.
- `wdLooks`: use the same badge, and skip the `own` map for pieces that already carry `photo`.
- `#wrun`: change the guard to `WD.items.length + WD.owned.length < 3`.
- `#wout`: add the "You own" row from `owned_in_looks`.
- `wdAddMenu`: add **Scan my real garment** when `/api/studio-config` returns `bo6_enabled: true`. It goes to `#bo6-add` and returns to `#wardrobe` after saving. The existing Take a photo stays.

Owned garments in this first version appear only in `#wardrobe`. Verdict, My Outfit, Daily Edit and BO3 stay catalog-only (Q7).

### User with no garments

No overlay is built, no keys are added, and `prefer` stays empty, so the path is the same code with the same output. This is tested by comparing responses with the flag on and off.

---

## 6. Embedding for new garments

1. **Compute:** `wardrobe.enc_image(A(), raw)`, the team's own code, using `laion2b_s34b_b79k`. Input is the private PNG read with `LocalPrivateStorage`.
2. **When:** lazily, on the first overlay build after a save, in `wardrobe_owned.py`. `app/garments/router.py` must not import `wardrobe.py`, which would load torch and the catalog into the Studio app and its tests. A failed encoding sets `failed` and the garment stays listed.
3. **Store:** float32 bytes (2 KB) in `clip_embedding`, with `embedding_model = "ViT-B-32/laion2b_s34b_b79k"`. A model mismatch resets the row to `pending`.
4. **Read:** the overlay stacks user rows with `a.EMB` for `pool`, and with `scoring._S["E"]` for scoring. These matrices are identical today. If the team later fine-tunes (`finetuned: true`), they diverge and this needs revisiting (Q2).

`emb_clip.npy`, `emb_ft.npy`, `catalog.json` and every other shared file stay untouched.

---

## 7. Implementation order

| # | Step | Files | Test | Undo |
|---|---|---|---|---|
| 0 | Prepare: teammates land Taste Studio, create `feature/bo6-wardrobe`, back up both databases, add ignore rules for `bo6_service/bundle_g2l/` **before copying the bundle** | `.gitignore` | `git status` clean; `git check-ignore` passes on the safetensors file | Delete branch |
| 1 | Embedding gate: run `enc_image` on 50 `data/img` files against their `EMB` rows, using a script outside the repo | None | Mean cosine ≥ 0.90 and top-1 self-retrieval ≥ 95%. Otherwise stop, Q2 | Nothing to undo |
| 2 | Unzip the bundle, create `.venv-bo6-g2l`, run `selftest.py` | `bo6_service/requirements-g2l.in` | Prints `"ok": true` | Delete venv and folder |
| 3 | G2L runtime, chosen when the bundle has `config.json` | `bo6_service/app/model_runtime.py`, new `g2l_runtime.py`, `schemas.py`, `scripts/dev/start.ps1` | New tests; 5 sample photos through `/analyze` and `/describe`; legacy tests still pass | `MODEL_BUNDLE_DIR` back to `bundle/` |
| 4 | Vocabulary | Files in 4.3 | `tests/test_garments.py` plus new values | Revert commit |
| 5 | Migration `0013` and model | `alembic/versions/`, `app/models.py` | `tests/test_migrations.py`, upgrade and downgrade on a database copy | `alembic downgrade -1` |
| 6 | Profile on save and PATCH | `app/garments/router.py`, `schemas.py` | One garment, one profile; category correction updates `outfit_cat` | Revert commit |
| 7 | Manual upload route and UI | `app/garments/router.py`, `static/studio.js`, `static/studio/wardrobe.js` | Stop BO6, add a garment manually | Revert commit |
| 8 | Overlay and flag | New `wardrobe_owned.py`, `wardrobe.py`, `scoring.py`, `app/config.py`, `api.py` | Flag-off and no-garment snapshots identical; two-user test | `BO6_ENABLED=0` |
| 9 | Frontend | `static/index.html` | Manual check with two accounts | `BO6_ENABLED=0`, revert commit |
| 10 | Section 9 checklist | None | All pass | |

---

## 8. Safety plan

- **Branch:** all work on `feature/bo6-wardrobe`. Nothing is committed to `main`.
- **Backups:** before step 5, stop the app and copy `var/dressme.sqlite` and `var/wardrobe.db`.
- **Migration:** additive, with a tested down-migration.
- **Images:** existing private storage. No new location to clean up.
- **Flag:** `BO6_ENABLED`, default off until section 9 passes. Off means `/me`, `/analyze`, `/complete`, `/outfits` and the wardrobe menu behave as today. The Studio pages keep working, as they do now.
- **Shared files:** no writes to `data/`.
- **Public repo:** the GitHub repo answered an unauthenticated API request, so treat it as public. The bundle README says Garments2Look images must stay private, and `.gitignore` covers only `bo6_service/bundle/*.pt`. A 351 MB `model.safetensors` would not be ignored without step 0.

**Rollback:**
1. Set `BO6_ENABLED=0` and restart. This covers most problems.
2. Set `MODEL_BUNDLE_DIR` back to `bo6_service/bundle` and restart BO6 on `.venv-bo6`.
3. Run `alembic downgrade -1`, or restore the backup. Garments saved under new vocabulary values would then need review.
4. Return to `main`.

---

## 9. Verification checklist

The brief's MinIO check becomes a private-storage check (Q1). All items must pass before merging.

- [ ] `selftest.py` prints `"ok": true`; the service answers on 5 sample garment photos.
- [ ] Upload and corrected save create one `garments` row, one profile row and one private image file, all under the right `user_id`.
- [ ] A and B are test users: A's garments are invisible to B through `/studio-api/garments`, `GET /garments/{id}`, the image URL, `/api/wardrobe/me`, `/complete`, and the UI.
- [ ] B cannot reach A's garment by sending A's public id in `items`.
- [ ] "Complete my wardrobe": A sees A's pieces marked "From your wardrobe"; B sees none.
- [ ] A new user, and any user with the flag off, gets byte-identical `/me`, `/analyze`, `/complete`, `/outfits` for the same inputs.
- [ ] Recommendations contain only catalog items.
- [ ] Verdict, My Outfit, Daily Edit and BO3 work for a user who has owned garments, with no 400s.
- [ ] Saving the wardrobe does not lose or duplicate owned garments; switching Women / Men leaves them intact.
- [ ] BO6 stopped: the app works, manual add works, and the UI offers it.
- [ ] Existing users: wardrobe list, completion and outfits behave as before.
- [ ] Deleting a garment removes the `garments` row, the profile row and the image file, and nothing else.
- [ ] `git status` shows no weights, bundle files or images; `data/` is unchanged.
- [ ] `pytest tests bo3/tests` and `pytest bo6_service/tests` pass.

---

## 10. Open questions

For Khaled:

- **Q1. Storage:** is MinIO a real requirement, perhaps on another machine or a future deployment? This plan uses `LocalPrivateStorage`. If MinIO is required, a storage class must be built and that is new infrastructure.
- **Q4. Bundle:** is `BO6_G2L_everything.zip` the intended bundle? The brief's path was still a placeholder. The same report shows fine-tuned ResNet-18 at macro-F1 0.880 against 0.794 for the shipped CLIP head. Is the CLIP head the deliberate choice?
- **Q5. Checkout:** does this work belong in `integration_DressMe` (`main`)? The uncommitted avatar-render feature exists only in `projet_integration`.

For teammates:

- **Q2. Embeddings:** can someone confirm the notebook in 1.7 produced the current `emb_clip.npy`, and from which image files? Is fine-tuning (`finetuned: true`) planned?
- **Q3. Migrations:** who owns the uncommitted `0012_taste_reactions`, and when does it land? `0013` must chain from it.
- **Q6. Men wardrobe:** should an owned `dress` or `jumpsuit` be scored? The plan says no, matching the catalog rule.
- **Q7. Scope:** should owned garments later reach Verdict, My Outfit, Daily Edit and BO3? Each validates against catalog ids, so this is separate work.
- **Q8. Starter pieces:** should the "owned" wording account for the 14 random pieces new users see as "their" wardrobe? Should they be labelled "starter"?
- **Q9. Try-on:** which new categories may try-on accept? The proposal is `blouse`, `cardigan` as `tops`, `pants` as `bottoms`, `jumpsuit` as `one-pieces`, and none for the rest. The BO7 owner should confirm.
- **Q10. CSRF:** `/api/wardrobe/*` writes have no CSRF check. This plan adds no new writes there. Should it be fixed separately?

---

## 11. Risks and effort

| Risk | Impact | Mitigation |
|---|---|---|
| `enc_image` does not match `emb_clip.npy` closely enough | Poor scores for owned garments | Step 1 gate runs before any code |
| Scorer was trained on studio product photos | Phone photos score unreliably | Treat scores as advisory; test with real photos in step 10 |
| Phone-photo category accuracy unknown; weak classes `jumpsuit` F1 0.45, `blouse` 0.54, `top` 0.56 | Wrong suggestions | User must confirm; `needs_user_review` always true |
| Low RAM (0.53 GB free; 8002 holds about 15.5 GB) | BO6 or app failures during testing | Replace BO6 on 18023, not add; stop 8001 services while testing, if agreed |
| Teammates edit `index.html`, `api.py`, `wardrobe.py` in parallel | Merge conflicts | Land Taste Studio first; keep logic in `wardrobe_owned.py` |
| `wardrobe.py` overlay misses an array access | Wrong item or 500 | Inventory found `a.CAT`, `a.EMB`, `a.BYCAT`, `a.it`, `a.scoring`, plus `style_matrix` and `color_model`; two-user test |
| Bundle or weights committed to a public repo | Licence and privacy exposure | Ignore rules first; final `git status` check |
| Two wardrobes confuse users ("My Wardrobe" against `#wardrobe`) | Support confusion | Owned pieces appear in both; full merge is out of scope |

**Effort estimate:** about 5-7 working days for one developer, excluding waits on teammates.

| Work | Days |
|---|---|
| Steps 0-2: preparation and gate | 0.5 |
| Step 3: G2L runtime | 1 |
| Steps 4-7: vocabulary, migration, profile, manual add | 1.5 |
| Step 8: overlay and flag | 1-1.5 |
| Step 9: frontend | 1 |
| Step 10: verification and fixes | 0.5-1.5 |
