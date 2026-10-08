import hashlib
import json
from pathlib import Path


def verify_bundle(bundle: Path) -> None:
    manifest_path = bundle / "checksums.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Model bundle integrity check failed: missing {manifest_path.name}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Model bundle integrity check failed: invalid checksums.json ({exc})") from exc
    failures = []
    for rel_path, expected in manifest.items():
        path = (bundle / rel_path).resolve()
        if bundle.resolve() not in path.parents:
            failures.append(f"unsafe manifest path: {rel_path}")
            continue
        if not path.is_file():
            failures.append(f"missing {rel_path}")
            continue
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                size += len(block)
                digest.update(block)
        if size != expected.get("bytes") or digest.hexdigest() != expected.get("sha256"):
            failures.append(f"checksum mismatch: {rel_path}")
    if failures:
        raise RuntimeError("Model bundle integrity check failed: " + "; ".join(failures))
