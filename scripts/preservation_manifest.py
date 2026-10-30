"""Record Git blob identity for every original tracked file without mutating history."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def blob_hash(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def main():
    unchanged, changed = {}, {}
    for record in git("ls-tree", "-rz", "HEAD").split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, original = metadata.decode().split()
        if kind != "blob":
            continue
        name = raw_path.decode("utf-8", "surrogateescape")
        current_path = ROOT / name
        if not current_path.is_file():
            changed[name] = {"baseline_blob_sha1": original, "current": "missing"}
            continue
        data = current_path.read_bytes()
        # Git's EOL filters can make clean Windows working bytes differ from the
        # committed blob. Compare the filtered Git identity before flagging edits.
        current_blob = blob_hash(data)
        if current_blob != original:
            current_blob = git("hash-object", f"--path={name}", str(current_path)).decode().strip()
        if current_blob == original:
            unchanged[name] = original
        else:
            changed[name] = {"baseline_blob_sha1": original, "current_sha256": hashlib.sha256(data).hexdigest()}
    new_files = {
        n.decode("utf-8", "surrogateescape")
        for n in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
        if n
    }
    new_files.update(
        n.decode("utf-8", "surrogateescape")
        for n in git("diff", "--name-only", "--diff-filter=A", "HEAD", "-z").split(b"\0")
        if n
    )
    output = {
        "baseline_commit": git("rev-parse", "HEAD").decode().strip(),
        "original_tracked_count": len(unchanged) + len(changed),
        "unchanged_count": len(unchanged),
        "changed_existing_count": len(changed),
        "unchanged_git_blob_sha1": unchanged,
        "changed_existing": changed,
        "new_files": sorted(name for name in new_files if name != "docs/PRESERVATION_MANIFEST.json"),
    }
    target = ROOT / "docs/PRESERVATION_MANIFEST.json"
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"baseline {output['baseline_commit']} original {output['original_tracked_count']} unchanged {len(unchanged)} changed {len(changed)} new {len(output['new_files'])}")
    for name in changed:
        print("changed", name)


if __name__ == "__main__":
    main()
