#!/usr/bin/env python3
"""Exercise F01 benchmark input/output contracts and evidence negative controls."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    binary = args.binary.resolve()
    spec = importlib.util.spec_from_file_location("f01_summary", Path(__file__).with_name("summarize.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = []
    matrix = module.summarize([args.matrix])
    checks.append({"name": "independent_matrix_validation", "status": "passed", "rows": matrix["validated_rows"], "sources": matrix["sources"]})
    raw = json.loads(args.matrix.read_text().splitlines()[0])
    bounded = next(json.loads(line) for line in args.matrix.read_text().splitlines() if json.loads(line)["budget"] == "1")
    mutations = {
        "wrong_publication_oracle": lambda row: row["output_digest"].update(fnv1a64="0000000000000000"),
        "missing_physical_fetch": lambda row: row["poll_work"].update(records_fetched=0),
        "wrong_stop_total": lambda row: row["stop_counts"].update(Error=1),
        "wrong_final_range": lambda row: row["final_checkpoint"].update(after_seq=0),
        "finite_cap_exceeded": lambda row: row.update(max_inspections_in_call=2),
        "wrong_service_sample_count": lambda row: row["victim_service_delay_ns"].update(sample_count=0),
    }
    for name, mutate in mutations.items():
        row = copy.deepcopy(bounded if name == "finite_cap_exceeded" else raw)
        mutate(row)
        try:
            module.validate(row)
        except ValueError:
            checks.append({"name": name, "status": "killed"})
        else:
            raise AssertionError(f"negative control survived: {name}")
    with tempfile.TemporaryDirectory(prefix="tool-contract-", dir=root / "build/f01") as temporary:
        directory = Path(temporary)
        base = [str(binary), "--records", "17", "--cases", "no-match", "--shapes", "small", "--partitions", "1", "--modes", "scan", "--budgets", "1", "--reps", "1"]
        invalid = (("--records", "0"), ("--records", "2000001"), ("--budgets", "0"), ("--reps", "0"), ("--partitions", "65536"), ("--candidate-every", "0"), ("--max-outputs", "0"), ("--modes", "unknown"), ("--shapes", "small,small"))
        for i, (option, value) in enumerate(invalid):
            output = directory / f"invalid-{i}.jsonl"
            result = subprocess.run([*base, option, value, "--output", str(output)], cwd=root, capture_output=True, text=True)
            assert result.returncode != 0 and not output.exists(), (option, value, result)
        checks.append({"name": "invalid_cli_rejected_before_output", "status": "passed", "cases": len(invalid)})
        sentinel = directory / "existing.jsonl"
        sentinel.write_text("retain existing output\n")
        before = sentinel.read_bytes()
        result = subprocess.run([*base, "--output", str(sentinel)], cwd=root, capture_output=True, text=True)
        assert result.returncode != 0 and sentinel.read_bytes() == before
        checks.append({"name": "existing_output_preserved", "status": "passed"})
        outside = root / "build" / f"f01-output-outside-{directory.name}.jsonl"
        result = subprocess.run([*base, "--output", str(outside)], cwd=root, capture_output=True, text=True)
        assert result.returncode != 0 and not outside.exists()
        checks.append({"name": "historical_output_namespace_protected", "status": "passed"})
        infeasible = directory / "infeasible.jsonl"
        result = subprocess.run([*base, "--records", "2000000", "--shapes", "variable", "--output", str(infeasible)], cwd=root, capture_output=True, text=True)
        rows = [json.loads(line) for line in infeasible.read_text().splitlines()]
        assert result.returncode != 0 and len(rows) == 1 and rows[0]["status"] == "infeasible" and "cap" in rows[0]["error"]
        checks.append({"name": "infeasible_fixture_recorded_without_timing", "status": "passed"})
        packed = directory / "packed-limit.jsonl"
        result = subprocess.run([*base, "--partitions", "65535", "--output", str(packed)], cwd=root, capture_output=True, text=True)
        rows = [json.loads(line) for line in packed.read_text().splitlines()]
        assert result.returncode != 0 and len(rows) == 1 and rows[0]["status"] == "infeasible"
        checks.append({"name": "legal_packed_K_still_obeys_resource_cap", "status": "passed"})
    result = {"schema": "tiplog.f01.benchmark-contract-check.v1", "status": "passed", "binary": str(binary), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "checks": checks}
    target = args.output.resolve()
    assert any(target.is_relative_to(root / prefix) for prefix in ("results/f01", "build/f01")), "output outside F01 namespaces"
    with target.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps({"status": "passed", "checks": len(checks), "matrix_rows": matrix["validated_rows"]}))


if __name__ == "__main__":
    main()
