"""Record figure-only compatibility; retain all original experiment identities."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = "py/tiplog_py/figures/tip.py"
AFTER = "f156ad50beb039315b48c95a9e10772a4e4d2c4377951f76562619489e8d758f"
TEST_AFTER = "5e1f0e84e70dfe84430fe6a92f9d49512de3c239cbc13a0440fd638bc04f49a8"
cache = {}


def sha(path):
    path = Path(path).resolve()
    if path not in cache:
        with path.open("rb") as stream:
            cache[path] = hashlib.file_digest(stream, "sha256").hexdigest()
    return cache[path]


before = json.loads((HERE / "before.json").read_text())
assert sha(ROOT / SOURCE) == AFTER
assert sha(ROOT / "py/tests/test_analysis_figures.py") == TEST_AFTER
original_source = next(v for v in before["snapshots"] if v["path"] == SOURCE)
record = {
    "status": "passed", "at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "scope": "Presentation-only: separate eight F12 arms, factorized legends, wrapped titles/footer and nonnegative slot axis. No statistical method, ratio, raw input, timing or engine change.",
    "source": SOURCE, "before_sha256": original_source["sha256"], "after_sha256": AFTER,
    "test_source_sha256": TEST_AFTER,
    "focused_check": "results/p6/figure-layout-focused-tests-20261025T043234.286174Z.json",
    "changes": [], "unchanged_provenances": [],
}
for item in before["snapshots"]:
    snapshot = ROOT / item["snapshot"]
    assert sha(snapshot) == item["sha256"]
    if item["path"] not in ("results/raw/P6/campaign-20261024/campaign-provenance.json",
                             "results/raw/P6/campaign-20261024/evaluation/provenance.json"):
        continue
    path = ROOT / item["path"]
    assert sha(path) == item["sha256"], "concurrent provenance modification"
    original = json.loads(snapshot.read_text())
    for section in ("source_files", "binaries", "inputs"):
        for entry in original[section]:
            expected = AFTER if entry["path"] == SOURCE else entry["sha256"]
            assert sha(ROOT / entry["path"]) == expected, (section, entry["path"])
    entries = [v for v in original["source_files"] if v["path"] == SOURCE]
    if not entries:
        record["unchanged_provenances"].append(item)
        continue
    assert len(entries) == 1 and entries[0]["sha256"] == original_source["sha256"]
    updated = copy.deepcopy(original)
    entry = next(v for v in updated["source_files"] if v["path"] == SOURCE)
    old_entry = copy.deepcopy(entry)
    entry.update(bytes=(ROOT / SOURCE).stat().st_size, sha256=AFTER)
    amendment = {
        "at_utc": record["at_utc"], "source": SOURCE,
        "original_figure_source_sha256": original_source["sha256"],
        "figure_source_sha256": AFTER,
        "reason": record["scope"], "original_provenance_snapshot": item["snapshot"],
        "original_provenance_sha256": item["sha256"],
        "compatibility_record": "results/p6/f12-layout-compatibility/compatibility.json",
        "note": "Original timing identities remain the actual experiment identities; this compatibility view allows postprocessing regeneration only.",
    }
    updated.setdefault("postprocessing_amendments", []).append(amendment)
    path.write_text(json.dumps(updated, indent=2) + "\n")
    restored = copy.deepcopy(updated)
    restored["postprocessing_amendments"].pop()
    if not restored["postprocessing_amendments"]:
        del restored["postprocessing_amendments"]
    next(v for v in restored["source_files"] if v["path"] == SOURCE).update(old_entry)
    assert restored == original
    record["changes"].append({"provenance": item["path"], "before": old_entry,
                              "after": entry, "amendment": amendment})
for item in before["numerical_artifacts_before"]:
    assert sha(ROOT / item["path"]) == item["sha256"]
record["numerical_artifacts_verified"] = before["numerical_artifacts_before"]
record["unique_files_hashed"] = len(cache)
(HERE / "compatibility.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({"status": "passed", "amended_provenances": len(record["changes"]),
                  "unchanged_provenances": len(record["unchanged_provenances"]),
                  "unique_files_hashed": len(cache)}))
