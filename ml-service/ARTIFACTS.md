# BO6 model artifacts for a fresh checkout

The BO6 inference code, metadata, taxonomy, test fixture, and checksum manifest are tracked. The two trained checkpoints are intentionally excluded from Git because redistribution rights have not been established:

- `ml-service/bundle/model_weights.pt` — classifier checkpoint
- `ml-service/bundle/attribute_heads.pt` — attribute-head checkpoint

Obtain the matching exported BO6 bundle from the project owner or an approved private project artifact. Copy only those two files into `ml-service/bundle/`; the expected sizes and SHA-256 digests are recorded in the tracked `ml-service/bundle/checksums.json`. Do not substitute another export. Keep the artifact private and do not publish it in GitHub, releases, or public storage.

The service calls `verify_bundle()` during startup and checks every manifest entry, including file existence, byte size, and SHA-256. Missing files or mismatches raise `RuntimeError` with a bundle-integrity message and prevent the service from starting. The Dockerfile runs `bundle/selftest.py` during image build, so a fresh checkout without the two local checkpoint files cannot build the ML service image until the matching approved artifacts are supplied. The same self-test checks the tracked synthetic parity fixture.

After placing the artifacts, run from `ml-service/`:

```powershell
python bundle/selftest.py
python -m pytest -q
```

The test suite loads the real bundle and therefore also requires both checkpoints. This artifact procedure does not change or regenerate the exported BO6 bundle or its manifest.
