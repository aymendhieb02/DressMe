# BO6 ↔ BO7 integration contracts

These contracts are requirements for future shared application work, not implemented application endpoints. Preserve the existing BO6 ML service API and taxonomy.

## Shared application boundary

- One authenticated application backend owns users, garments, person photos, jobs, generated results, and private storage keys.
- Every record/file lookup and mutation includes the authenticated owner in its access predicate. The browser never calls BO6 or BO7 inference directly.
- BO6 and BO7 inference stay separate from application APIs. The backend supplies authorized inputs and persists outputs/metadata.
- Do not create a BO7 account system, duplicate wardrobe, second BO6 classifier, or public static directory for private media.

## BO6 service contract (verified)

- Internal endpoints: `GET /health`, `POST /analyze` (multipart field `image`), `POST /describe` (JSON `confirmed`). Details and response semantics are in `REPOSITORY_AUDIT.md` and `ml-service/app/`.
- Keep taxonomy `dressme-v0.2` and prediction/provenance snapshots. Never present uncalibrated scores as probabilities. Quality warnings are advisory, and user review is required.
- Current BO6 model categories and proposed FASHN mapping to validate with the product owner:

| BO6 category | Proposed FASHN category | Status |
|---|---|---|
| `t-shirt`, `shirt`, `top`, `sweater`, `sweatshirt` | `tops` | Candidate only; research rows require image inspection and are not validated for product use |
| `jeans`, `trousers`, `shorts`, `skirt` | `bottoms` | Candidate mapping; confirm in Phase 1 |
| `dress` | `one-pieces` | Research evidence maps Dresses to `one-pieces`, still marked for image inspection |
| `jacket` | Not eligible yet | Research row proposes `tops`, but compatibility is unverified; keep blocked until image-based/product validation |

The archived `bo6_vton_category_mapping.csv` maps candidate dataset labels and marks mapped apparel rows “Candidate single garment; inspect images”. It supports the table above as a starting point, not a validated BO6 taxonomy mapping: no human validation of these exact BO6 prediction classes is recorded. The model may predict a class unfit for VTON. The user must review the category, and an unmapped item cannot be submitted for try-on until a supported policy is agreed. Jackets are not automatically eligible until their compatibility is established. No taxonomy change is authorized by this audit.

## Garment additions needed by BO7

- Add a reviewable garment photo type with values `flat-lay` or `model`, persisted with the shared garment and exposed to the owner.
- Keep the BO6 class, confirmed attributes, original image reference, prediction/quality snapshots, and provenance. Keep an explicit FASHN category mapping separate from the BO6 taxonomy.
- Ensure person photo and garment image are private objects with owner checks, opaque keys, and a documented deletion lifecycle.

## Try-on submission and job contract (to design in Phase 2+)

- Accept only a garment and person-photo reference owned by the caller, an allowed mapped FASHN category, explicit photo-upload consent, and an idempotency key.
- Preserve the existing mock API v1 idempotency behavior and structured error envelope after the mock API is inspected; no such API was found in this checkout.
- Persist owner/input references, garment ID/photo type, model/revision, effective settings, input SHA-256 hashes, timings, peak GPU memory, state, errors, and private output key.
- Use states `queued`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`. Report named states; do not invent percentage progress.
- Defaults requested by the task: pretrained FASHN VTON v1.5, float16, 15 steps, guidance 1.5, seed 42, `segmentation_free=true`, `num_samples=1`. Reject real inference if dtype/provider verification fails. Mock mode remains GPU-free.
- The worker is a separate process/service, loads the model once when feasible, serializes GPU inference initially, verifies pose ONNX providers use CUDA, and enforces killable process timeouts.

## Privacy and deletion

Require explicit consent before person-photo upload. Keep generated previews and person photos private and owner-scoped. A future deletion implementation must define behavior for queued jobs (cancel and delete inputs), running jobs (terminate or mark cancellation and clean artifacts), completed jobs (delete result and its private file), and account deletion (remove or anonymize all owned records and files in a documented order). No such lifecycle exists yet.
