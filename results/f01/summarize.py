#!/usr/bin/env python3
"""Validate F01 raw rows and summarize paired repetition distributions.

Uses only the standard library. The input JSONL remains the primary evidence;
these medians do not pool calls or manufacture percentile sample counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

WORK_FIELDS = (
    "bytes_inspected", "entries_visited", "records_fetched", "delivered",
    "pads_inspected", "seek_data_examined", "seek_pads_examined", "index_seeks",
)
IDENTITY = (
    "records", "seed", "case", "shape", "configured_partitions", "candidate_every", "mode", "kernel",
    "budget", "schedule", "max_outputs",
)
STOPS = ("NoWork", "OutputLimit", "InspectionLimit", "SnapshotDone", "CaughtUp", "Error")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def uint(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name}: expected nonnegative integer")
    return value


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(row):
    require(row["schema"] == "tiplog.f01.poll-benchmark.v1", "unknown raw schema")
    require(row["status"] == "ok", f"non-ok outcome retained: {row.get('error', row['status'])}")
    require(row["reader"] == "replay" and row["correctness"] == "passed", "unexpected reader/correctness status")
    n = uint(row["records"], "records")
    calls = uint(row["calls"], "calls")
    require(0 < n <= 2_000_000 and calls > 0, "invalid record/call count")
    require(row["shape"] in ("small", "fixed", "variable", "wrapped-variable"), "unknown shape")
    require(row["mode"] in ("scan", "indexed", "auto") and row["effective_mode"] in ("scan", "indexed"), "unknown mode")
    require(row["kernel"] in ("stdpq", "binheap", "quad", "loser"), "unknown kernel")
    require(row["schedule"] in ("round-robin", "immediate-redrain"), "unknown schedule")
    require(row["fixture_reserved_bytes"] <= 128 << 20, "fixture cap exceeded")
    require(row["fixture_selected_partitions"] == row["configured_partitions"], "fixture selected K mismatch")
    require(row["output_digest"] == row["oracle_digest"], "output differs from publication oracle")
    stride = uint(row["candidate_every"], "candidate_every")
    require(0 < stride <= 1024, "invalid candidate stride")
    candidates = (n - 1) // stride + 1 + int((n - 1) % stride != 0)
    require(row["fixture_candidate_records"] == candidates, "candidate fixture count mismatch")
    expected_outputs = {"no-match": 0, "late-match": 1, "sparse": candidates // 128, "dense": candidates}[row["case"]]
    require(row["oracle_digest"]["outputs"] == expected_outputs, "independent case output count mismatch")
    require(row["final_checkpoint"]["after_seq"] == n + row["fixture_priming_records"], "final range mismatch")
    require(row["max_outputs_in_call"] <= row["max_outputs"], "output cap exceeded")
    require(row["zero_output_calls"] <= calls, "zero-output count exceeds calls")
    for field in WORK_FIELDS:
        for section in ("open_work", "poll_work", "all_work"):
            uint(row[section][field], f"{section}.{field}")
        require(row["all_work"][field] == row["open_work"][field] + row["poll_work"][field], f"work sum mismatch: {field}")
    work = row["poll_work"]
    require(work["delivered"] == expected_outputs, "delivery counter mismatch")
    if row["effective_mode"] == "indexed":
        require(work["records_fetched"] == candidates and work["entries_visited"] == candidates and work["pads_inspected"] == 0, "indexed accounting mismatch")
        units = work["entries_visited"]
        require(work["bytes_inspected"] <= row["fixture_data_bytes"], "indexed DATA spans exceed fixture")
    else:
        require(work["records_fetched"] == n, "scan did not fetch every primary DATA")
        require(work["entries_visited"] == 0 and work["pads_inspected"] == row["fixture_pads_in_range"], "scan PAD/accounting mismatch")
        units = work["records_fetched"] + work["pads_inspected"]
        require(work["bytes_inspected"] >= row["fixture_data_bytes"], "scan DATA spans incomplete")
    require(row["inspections_used"] == units, "inspection total disagrees with physical work")
    budget = row["budget"]
    if budget not in ("legacy", "unlimited"):
        cap = int(budget)
        require(cap > 0 and row["max_inspections_in_call"] <= cap, "finite inspection cap exceeded")
        require(units <= calls * cap, "aggregate inspection cap exceeded")
        if row["case"] == "no-match":
            require(calls == math.ceil(units / cap), "rejecting range did not make exact budgeted progress")
    require(set(row["stop_counts"]) == set(STOPS), "unknown/missing stop reason")
    for count in row["stop_counts"].values():
        uint(count, "stop count")
    require(sum(row["stop_counts"].values()) == (0 if budget == "legacy" else calls), "stop count total mismatch")
    require(row["stop_counts_available"] is (budget != "legacy"), "legacy stop availability mismatch")
    require(row["stop_counts"]["Error"] == 0 and row["stop_counts"]["CaughtUp"] == 0 and row["stop_counts"]["NoWork"] == 0, "unexpected stop")
    services = calls if row["schedule"] == "round-robin" else 1
    require(row["service_calls"] == services, "service policy mismatch")
    for field, expected in (("poll_latency_ns", calls), ("victim_service_delay_ns", services), ("publisher_service_delay_ns", services)):
        sample = row[field]
        for key in ("sample_count", "p50", "p95", "p99", "max", "sum"):
            uint(sample[key], f"{field}.{key}")
        require(sample["sample_count"] == expected, "percentile sample count mismatch")
        require(sample["p50"] <= sample["p95"] <= sample["p99"] <= sample["max"] <= sample["sum"], "unordered/inconsistent sample statistics")
    require(row["drain_elapsed_ns"] >= row["poll_latency_ns"]["sum"], "poll time exceeds drain time")
    require(row["drain_cpu_ns"] > 0 and row["open_elapsed_ns"] > 0, "invalid timing")
    return tuple(row[key] for key in IDENTITY)


def median(rows, field, subfield=None):
    return statistics.median(row[field][subfield] if subfield else row[field] for row in rows)


def summarize(paths):
    groups = {}
    seen = set()
    sources = []
    for path in paths:
        data = path.read_bytes()
        sources.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        for line_number, line in enumerate(data.splitlines(), 1):
            try:
                row = json.loads(line, object_pairs_hook=unique_object)
                key = validate(row)
                identity = (*key, uint(row["repetition"], "repetition"))
                require(identity not in seen, "duplicate arm/repetition identity")
                seen.add(identity)
                groups.setdefault(key, []).append(row)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    require(groups, "no raw rows")
    summaries = []
    for key, rows in sorted(groups.items()):
        item = dict(zip(IDENTITY, key, strict=True))
        item.update({
            "repetitions": len(rows),
            "repetition_labels": sorted(row["repetition"] for row in rows),
            "calls_median": median(rows, "calls"),
            "inspections_median": median(rows, "inspections_used"),
            "outputs": rows[0]["output_digest"]["outputs"],
            "effective_mode": rows[0]["effective_mode"],
            "poll_sample_counts": [row["poll_latency_ns"]["sample_count"] for row in rows],
            "poll_p50_ns_median": median(rows, "poll_latency_ns", "p50"),
            "poll_p95_ns_median": median(rows, "poll_latency_ns", "p95"),
            "poll_p99_ns_median": median(rows, "poll_latency_ns", "p99"),
            "poll_max_ns_observed": max(row["poll_latency_ns"]["max"] for row in rows),
            "poll_sum_ns_median": median(rows, "poll_latency_ns", "sum"),
            "open_ns_median": median(rows, "open_elapsed_ns"),
            "drain_elapsed_ns_median": median(rows, "drain_elapsed_ns"),
            "drain_cpu_ns_median": median(rows, "drain_cpu_ns"),
            "victim_p99_ns_median": median(rows, "victim_service_delay_ns", "p99"),
            "publisher_p99_ns_median": median(rows, "publisher_service_delay_ns", "p99"),
            "service_sample_counts": [row["service_calls"] for row in rows],
            "index_seeks_median": median(rows, "poll_work", "index_seeks"),
            "max_inspections_in_call": max(row["max_inspections_in_call"] for row in rows),
        })
        # Ratios are paired by repetition rather than ratios of pooled medians.
        reference_key = list(key)
        reference_key[IDENTITY.index("budget")] = "legacy"
        references = {row["repetition"]: row for row in groups.get(tuple(reference_key), [])}
        pairs = [(row, references[row["repetition"]]) for row in rows if row["repetition"] in references]
        item["legacy_pair_count"] = len(pairs)
        if pairs:
            item["poll_sum_ratio_to_legacy_median"] = statistics.median(row["poll_latency_ns"]["sum"] / old["poll_latency_ns"]["sum"] for row, old in pairs)
            item["drain_elapsed_ratio_to_legacy_median"] = statistics.median(row["drain_elapsed_ns"] / old["drain_elapsed_ns"] for row, old in pairs)
        summaries.append(item)
    return {"schema": "tiplog.f01.poll-summary.v1", "status": "passed", "validated_rows": len(seen), "sources": sources,
            "interpretation": "Exact per-repetition percentiles, then median across repetitions; max is an observed maximum. Timings include public setup. Shared-host observations carry no hard latency or quiet-host guarantee. Round-robin service counts differ with poll count.", "arms": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, help="new summary JSON; existing files refused")
    args = parser.parse_args()
    result = summarize(args.inputs)
    if args.output:
        project = Path(__file__).resolve().parents[2]
        destination = args.output.resolve()
        require(any(destination.is_relative_to(project / folder) for folder in ("results/f01", "build/f01")), "summary output must be beneath results/f01 or build/f01")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as output:
            json.dump(result, output, indent=2, allow_nan=False)
            output.write("\n")
    print(json.dumps({"status": "passed", "validated_rows": result["validated_rows"], "arms": len(result["arms"])}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"f01 summary: {error}", file=sys.stderr)
        raise SystemExit(1)
