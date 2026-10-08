# BO7 architecture handoff — source document unavailable

> **Status:** The requested original `ARCHITECTURE_HANDOFF.md` was not present in this checkout. The supplied archives were inspected; none contains that filename. This file is a clearly labelled Phase 0 handoff record, not a copy or replacement of the missing source document. The user's BO7 task brief and the existing root `ARCHITECTURE_ROADMAP.md` are the available planning inputs. Update this page when the original handoff is supplied.

## Confirmed direction from the task brief

- BO6 and BO7 remain one DressMe application with one React + TypeScript + Vite frontend, one shared FastAPI application backend, one authentication system, one PostgreSQL database, and shared user/garment identity and private storage.
- Keep the existing BO6 inference service separate from the application backend. The browser must call only the application backend; the backend calls inference services privately.
- BO7's model choice is pretrained FASHN VTON v1.5. No LoRA, fine-tuning, CatVTON implementation, or new model is in scope.
- The requested BO7 real-inference settings are float16, 15 steps, guidance 1.5, seed 42, segmentation-free enabled, and one sample. Real inference must fail closed unless float16 and CUDA pose execution are verified.
- Supported FASHN categories are `tops`, `bottoms`, and `one-pieces`. Garments record a user-reviewable `garment_photo_type` of `flat-lay` or `model`.
- Mock mode must remain usable without a GPU. Try-on jobs are asynchronous, owner-scoped, idempotent, auditable, and use the states `queued`, `running`, `succeeded`, `failed`, `timed_out`, and `cancelled`.
- This is an academic, non-commercial prototype. Person photos/results are private, uploads require explicit consent, and the UI includes “Academic prototype — non-commercial” and “AI-generated preview, not an exact fit”.

## Open decisions and conflicts to resolve

1. The archived standalone FASHN package declares 20-step preview and 30-step balanced presets, whereas the task brief requires 15 steps. Do not wire the archived defaults into an API until the owner confirms the frozen contract; Phase 0 records the task brief's 15-step requirement as the requested target.
2. The archive's status ledger says the weight manifest, clean-worker restoration, real smoke test, and ONNX provider verification are not verified. No production or GPU readiness claim follows from the bundle's presence.
3. The archive's licence audit identifies a non-commercial NVIDIA SegFormer source licence in the human-parser dependency and says other model/deployment terms remain incompletely verified. Keep the prototype non-commercial and do not redistribute private weights.
4. BO6 categories do not map one-to-one to FASHN categories. Define and validate a mapping against confirmed BO6 garments; reject unsupported categories instead of guessing.
5. The root BO6 roadmap proposes the shared backend, auth, PostgreSQL, SQLAlchemy/Alembic, and private storage, but those components do not exist in this checkout.

## Required follow-up

Supply the original architecture handoff and reconcile it with this audit before implementation tasks rely on it as a source document. See `REPOSITORY_AUDIT.md`, `INTEGRATION_CONTRACTS.md`, and `IMPLEMENTATION_ROADMAP.md` for verified repository facts and the Phase 0 plan.
