# BO7 implementation status

Last updated: 2026-10-08.

## Phase 0 — PARTIALLY COMPLETE

- **Local shared baseline:** `main` points to `63d1904`, containing BO6 service source/tests/configuration and BO7 FASHN source. The baseline also tracks research PDFs, a BO6 notebook, and small research ZIPs; the PDFs contain human-model imagery whose provenance/privacy/publication rights remain under review.
- **BO7 integration:** Local branch `BO7` preserves the two documentation commits and has merge commit `36ab05c` integrating `main`. The remote `BO7` branch has not been verified or published.
- **Remote:** The public repository's observed refs were `main` and `feature/bo6-implementation`, both at `63d1904`. `main` is already on the remote. No remote `BO7` ref was observed.
- **Connectivity:** A temporary process-scoped no-proxy Git request worked. GitHub CLI is absent. Git Credential Manager is configured but push authentication has not been verified.
- **BO6 tests:** `pytest -q` in `ml-service/` passed 13 tests on the local checkout with one deprecation warning. The matching model files are present locally but excluded from Git.
- **Architecture handoff:** Original source not found in the checkout or inspected archives. The committed handoff record is explicitly provisional.
- **BO7 runtime:** Pretrained FASHN VTON v1.5 source package is present, but no unified-app BO7 API/worker is implemented. Task target is 15 steps with float16, guidance 1.5, seed 42, segmentation-free, one sample; real GPU execution, CUDA pose providers, and this target configuration are unverified. The archived source config's 20/30-step presets conflict with the target.
- **Category mapping:** Research mappings remain candidates pending image-based validation. Jackets are blocked from try-on by default until compatibility is established.
- **Hybrid Avatar:** V1.4 validation on real user photos remains pending; automatic initialization, manual editing, persistence, and product integration are not proven.

## Remaining Phase 0 gates

1. Resolve whether the committed BO6/BO7 research reports and notebook, including their model imagery, may remain in the public repository history. Do not rewrite history; if they must be removed from public history, obtain an approved migration plan before changing it.
2. Once the public-content review is resolved, verify GitHub push authentication locally and publish `BO7`; verify remote head hashes and upstream tracking for `main` and `BO7`.
3. Run `docker compose config --quiet` and rerun `pytest -q` after final documentation changes.

## Smallest Phase 1 task

Validate the BO6-to-FASHN category mapping against actual garment images and record an explicit eligibility decision for each of the 11 BO6 classes. Keep jackets ineligible until compatibility is established. Do not start shared backend implementation in this Phase 0 task.
