"""Compare one persisted summary cohort with its current immutable noise sidecar."""
import json
from pathlib import Path
from tiplog_py.analysis.summarize import hydrate_noise

root = Path(__file__).resolve().parents[3]
manifest = json.loads((root / "results/p6/analysis-inputs.json").read_text())
source = root / manifest["sources"][0]["path"]
with source.open() as stream:
    selected = json.loads(next(stream))
key = selected["exp"], selected["config_id"]
cache, observations = {}, []
with source.open() as stream:
    for line in stream:
        row = json.loads(line)
        if (row["exp"], row["config_id"]) == key and not row.get("warmup", False):
            hydrate_noise(row, source_path=source, cache=cache)
            observations.append(row)
saved = json.loads((root / "results/derived/tip-summary.json").read_text())
cohort = next(row for row in saved["configurations"] if (row["exp"], row["config_id"]) == key)
fields = ("noise_flagged_count", "noise_observed_count", "noise_unknown_count")
actual = dict(zip(fields, (
    sum(row.get("noise_flagged") is True for row in observations),
    sum(isinstance(row.get("noise_flagged"), bool) for row in observations),
    sum(not isinstance(row.get("noise_flagged"), bool) for row in observations))))
result = {"exp": key[0], "config_id": key[1], "n_measured": len(observations),
          "saved_summary": {field: cohort[field] for field in fields},
          "current_sidecar_reconstruction": actual,
          "sidecar": observations[0]["frequency_flags_reference"]}
print(json.dumps(result, indent=2))
assert result["saved_summary"] != actual
