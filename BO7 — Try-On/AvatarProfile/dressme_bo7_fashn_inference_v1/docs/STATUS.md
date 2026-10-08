# Status ledger (what is verified and what is not) — update this file, never just the chat

| Item | Status | Evidence |
|---|---|---|
| FASHN pipeline runs on Kaggle T4 (30 and 20 steps), outputs saved | **VERIFIED** (research baseline) | Phase 3/3b/4A notebooks |
| Standalone script imports real `fashn_vton`, validates params, fails cleanly on missing weights/manifest | **VERIFIED** (CPU sandbox, no weights) | API test `test_real_worker_startup`, `tests/test_bundle.py` |
| Weights SHA-256 manifest | **NOT YET GENERATED** — created by running the Kaggle export cell (tools/make_manifest.py) | — |
| Offline weights bundle built and hash round-trip checked | **NOT VERIFIED** until the export cell is run | — |
| Restoration on a clean worker + real 20-step inference via standalone script | **NOT VERIFIED** — must run `tools/smoke_test.py` on a fresh GPU session | smoke_test_evidence.json (absent) |
| ONNX providers actually used (CUDA vs CPU) | **NOT VERIFIED** — recorded by the smoke test | — |
| Human parser licence permits commercial use | **NO** (non-commercial, READ) | licenses/ |
