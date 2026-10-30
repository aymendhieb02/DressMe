# BO6/BO7 migration map

| Source | Integrated path | Contract/preservation |
|---|---|---|
| `backend/app/**` | `app/**` | Reused Python API, models, auth, owner checks, storage, avatar and try-on queue logic without changing endpoint semantics. |
| `backend/alembic/**`, `alembic.ini` | `alembic/**`, `alembic.ini` | Existing migrations through `0008_private_avatar_renders` applied to a fresh dedicated database. |
| `backend/requirements.in` | `requirements-studio.in` | Existing pinned app dependencies included by root `requirements.txt`. |
| `ml-service/app/**` | `bo6_service/app/**` | One CPU inference service, private backend dependency. |
| `ml-service/bundle/**` | `bo6_service/bundle/**` | Code/metadata copied; `.pt` files restored locally but ignored in Git. Manifest and self-test check exact bundle. |
| `frontend/src/App.tsx`, `GarmentDetail.tsx`, `api.ts` | `static/studio.js`, `static/studio.css` | Vanilla UI for auth, upload/review/description, wardrobe/detail/edit, person photo, mock job/history and partial avatar handling. The existing React app is not embedded. |
| `frontend/src/AvatarPage.tsx`, avatar provider/render modules | Partial in `static/studio.js`, vendored SDK/viewer in `static/vendor/` | Current avatar read/delete, GLB import, private 3D viewer and gated Avaturn creator/export integration ported. Actual provider session/export and PNG render capture/save remain unverified. |
| BO7 notebook/model experiments | No production adapter | No copied model weights, training, licensed redistribution or real generation claim. |

The team application's five original sections, their IDs, markup and endpoint prefixes remain intact. Additive integration touchpoints are the My Studio menu entries, new sections, one section event dispatch, one mounted API and the new static module/style.

The versioned BO6 record retains owned garment UUID, private image key (server only), normalized class and taxonomy version, dimensions through the pending upload, confirmed metadata, raw prediction snapshot/provenance, and eligibility snapshot. BO7 job creation resolves the owned garment/photo server-side and snapshots their revisions. Masks are optional and currently unavailable. Deleting or changing inputs is governed by the copied backend job contract.
