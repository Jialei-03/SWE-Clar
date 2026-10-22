import hashlib, json
from pathlib import Path
root = Path(__file__).resolve().parent
rows = json.loads((root / "implementations.json").read_text())
assert len(rows) == 300
assert len({r["task"] for r in rows}) == 100
for task in {r["task"] for r in rows}:
    assert {r["variant"] for r in rows if r["task"] == task} == {"reference", "equivalent", "incorrect"}
for row in rows:
    base = root / "implementations" / row["task"] / row["variant"]
    assert hashlib.sha256((base / "implementation.patch").read_bytes()).hexdigest() == row["distributed_source_patch_sha256"]
    for name, digest in row["files"].items():
        assert hashlib.sha256((base / "workspace" / name).read_bytes()).hexdigest() == digest, (row["task"], name)
print("Verified implementation coverage and source file hashes.")
