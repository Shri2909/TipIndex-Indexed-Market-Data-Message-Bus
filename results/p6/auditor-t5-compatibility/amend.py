"""Record a narrowly scoped postmeasurement auditor compatibility amendment."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = "scripts/check_p6_experiments.py"
BEFORE = "8a6943f3bf21343e5901bf1a60bbd2dcaa8f5c69343c3082b77146b265e5c2ab"
AFTER = "2531f9e9c5f4a8272a207522edb92055b7fe20e44f46deac2efc0d290fb16f44"
cache = {}


def sha(path):
    path = Path(path).resolve()
    if path not in cache:
        with path.open("rb") as stream:
            cache[path] = hashlib.file_digest(stream, "sha256").hexdigest()
    return cache[path]


assert sha(HERE / "0-check_p6_experiments.py") == BEFORE
assert sha(ROOT / SOURCE) == AFTER
record = {
    "status": "passed",
    "at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "scope": "Postprocessing-only auditor correction. No engine, benchmark, driver, input, threshold, matrix, timing or acceptance criterion changed.",
    "source": SOURCE,
    "before_sha256": BEFORE,
    "after_sha256": AFTER,
    "changes": [],
    "self_test": "results/p6/auditor-t5-enrichment-self-test-20261025T041647.001633Z.json",
    "failed_original_audit": "results/p6/auditor-t5-compatibility/1-independent-audit.json",
    "measurement_inventory": "results/p6/auditor-t5-compatibility/measurement-files-before.json",
}
before = json.loads((HERE / "before.json").read_text())
for item in before["snapshots"][2:]:
    original_path = ROOT / item["snapshot"]
    path = ROOT / item["path"]
    assert sha(original_path) == item["sha256"]
    assert sha(path) == item["sha256"], "concurrent provenance modification"
    original = json.loads(original_path.read_text())
    for section in ("source_files", "binaries", "inputs"):
        for entry in original[section]:
            actual = ROOT / entry["path"]
            expected = AFTER if entry["path"] == SOURCE else entry["sha256"]
            assert sha(actual) == expected, (section, entry["path"])
            if entry["path"] != SOURCE and "bytes" in entry:
                assert actual.stat().st_size == entry["bytes"]
    changed = copy.deepcopy(original)
    entries = [v for v in changed["source_files"] if v["path"] == SOURCE]
    assert len(entries) == 1
    assert entries[0]["sha256"] == BEFORE
    old_entry = copy.deepcopy(entries[0])
    entries[0].update(sha256=AFTER, bytes=(ROOT / SOURCE).stat().st_size)
    amendment = {
        "at_utc": record["at_utc"],
        "reason": "Validate intentional T5 allocator enrichment against independent raw allocator arithmetic while retaining exact replay-counter equality.",
        "source": SOURCE,
        "original_execution_auditor_sha256": BEFORE,
        "auditor_sha256": AFTER,
        "original_provenance_snapshot": item["snapshot"],
        "original_provenance_sha256": item["sha256"],
        "compatibility_record": "results/p6/auditor-t5-compatibility/compatibility.json",
        "note": "Compatibility view only; original execution provenance and failed audit remain immutable snapshots.",
    }
    changed.setdefault("postprocessing_amendments", []).append(amendment)
    path.write_text(json.dumps(changed, indent=2) + "\n")
    restored = copy.deepcopy(changed)
    restored["postprocessing_amendments"].pop()
    if not restored["postprocessing_amendments"]:
        del restored["postprocessing_amendments"]
    next(v for v in restored["source_files"] if v["path"] == SOURCE).update(old_entry)
    assert restored == original, "more than the declared source entry/annotation changed"
    record["changes"].append({"provenance": item["path"], "before": old_entry,
                              "after": entries[0], "amendment": amendment})
record["other_unique_files_verified"] = len(cache) - 3
(HERE / "compatibility.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({"status": "passed", "amended_provenances": len(record["changes"]),
                  "unique_files_hashed": len(cache), "one_changed_source": SOURCE}))
