#!/usr/bin/env python3
"""Report-only T2 cohort CPU summaries and whole-round adjusted-cost ratios.

Reads persisted observations only. It never runs an engine or changes raw data.
The signed publisher index-on/off delta is charged once per indexed cohort,
using the publisher window's own duration, and is not charged to Scan.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py"))
from tiplog_py.analysis.stats import median_summary, paired_ratio, stable_seed
from tiplog_py.analysis.summarize import arm, usable


def metrics(row):
    work, config = row["work"], row["config"]
    recovery, duration = row["cpu_ns"], config["market_seconds"]
    publisher_duration = work["publish_window_market_seconds"]
    delta = work["publish_index_on_cpu_ns"] - work["publish_index_off_cpu_ns"]
    if not all(math.isfinite(x) for x in (recovery, duration, publisher_duration, delta)):
        raise ValueError("non-finite T2 cost")
    if recovery < 0 or duration <= 0 or publisher_duration <= 0:
        raise ValueError("invalid T2 duration")
    recovery_rate = recovery / duration / 1e9
    index_rate = delta / publisher_duration / 1e9
    charged = 0.0 if arm(row) == "scan" else index_rate
    return {"cpu_ns": recovery, "cpu_per_market_second": recovery_rate,
            "adjusted_cpu_per_market_second": recovery_rate + charged,
            "publish_index_delta_cpu_ns": delta,
            "charged_amortized_index_cpu_ns": charged * duration * 1e9}


def summarize(rows, *, repetitions=20, seed=20191230):
    groups = defaultdict(lambda: defaultdict(list))
    warmups, observed = defaultdict(Counter), 0
    for row in rows:
        if row.get("exp") != "T2":
            continue
        observed += 1
        if row.get("warmup"):
            warmups[row["comparison_id"]][arm(row)] += 1
            continue
        groups[row["comparison_id"]][arm(row)].append(row)
    cohorts, comparisons = [], []
    required_arms = {"scan"} | {f"{mode}/{kernel}" for mode in ("indexed", "auto")
                              for kernel in ("stdpq", "binheap", "quad", "loser")}
    seen_cohorts = set()
    for identity, arms in sorted(groups.items()):
        if set(arms) != required_arms:
            raise ValueError(f"{identity}: incomplete arm coverage")
        example = arms["scan"][0]
        config = example["config"]
        cohort = {"comparison_id": identity, "workload_id": example["workload_id"],
                  "readers": config["R"], "cache": example["cache"],
                  "market_seconds": config["market_seconds"], "arms": {}}
        key = (cohort["readers"], cohort["cache"])
        if (key in seen_cohorts or set(warmups[identity]) != required_arms
                or any(count != 1 for count in warmups[identity].values())):
            raise ValueError("duplicate cohort or missing/duplicate saved warm-up")
        seen_cohorts.add(key)
        blocks = {}
        for name, observations in sorted(arms.items()):
            if (len(observations) != repetitions or
                    {row["rep"] for row in observations} != set(range(repetitions))):
                raise ValueError(f"{identity}/{name}: missing or duplicate measured round")
            if len({row["process_round_id"] for row in observations}) != repetitions:
                raise ValueError(f"{identity}/{name}: reused process identity")
            if any(row["comparison_id"] != identity or row["config"]["R"] != cohort["readers"]
                   or row["cache"] != cohort["cache"] for row in observations):
                raise ValueError("mixed cohort semantics")
            valid = [row for row in observations if usable(row)]
            values = [metrics(row) for row in valid]
            summary = {"n": len(observations), "n_ok": len(valid),
                       "status_counts": dict(Counter(row["status"] for row in observations)),
                       "delivered_counts": sorted({row["out_count"] for row in valid}),
                       "raw_evidence": sorted({row["raw_path"] for row in observations}),
                       "metrics": {}}
            if values:
                for metric in values[0]:
                    summary["metrics"][metric] = median_summary(
                        [value[metric] for value in values],
                        seed=stable_seed(seed, f"T2-adjusted/{identity}/{name}/{metric}"))
            cohort["arms"][name] = summary
            blocks[name] = {str(row["paired_round_id"]): [value["adjusted_cpu_per_market_second"]]
                            for row, value in zip(valid, values)}
            if len(blocks[name]) != len(valid):
                raise ValueError("duplicate paired round")
        for name in sorted(required_arms - {"scan"}):
            item = {"comparison_id": identity, "readers": cohort["readers"],
                    "cache": cohort["cache"], "numerator": "scan", "denominator": name,
                    "metric": "adjusted_cpu_per_market_second",
                    "raw_evidence": sorted(set(cohort["arms"]["scan"]["raw_evidence"] +
                                                cohort["arms"][name]["raw_evidence"]))}
            eligible = (len(blocks["scan"]) == len(blocks[name]) == repetitions
                        and set(blocks["scan"]) == set(blocks[name])
                        and all(value[0] > 0 for name2 in ("scan", name)
                                for value in blocks[name2].values()))
            if eligible:
                item.update(status="ok", **paired_ratio(blocks["scan"], blocks[name],
                    seed=stable_seed(seed, f"T2-adjusted/{identity}/{name}")))
            else:
                item.update(status="withheld_incomplete_or_nonpositive", ratio=None,
                            ci95_low=None, ci95_high=None)
            comparisons.append(item)
        cohorts.append(cohort)
    if seen_cohorts != {(readers, cache) for readers in (1, 10, 100, 1000)
                        for cache in ("repeat-warm", "scratch-thrashed")}:
        raise ValueError("incomplete approved T2 cohort matrix")
    return {"schema": 1, "status": "passed", "repetitions": repetitions,
            "seed": seed, "bootstrap_resamples": 10000,
            "formula": "Scan: reader_CPU_ns / reader_market_seconds / 1e9; Indexed/Auto: Scan-rate formula plus (publisher_on_ns - publisher_off_ns) / publisher_market_seconds / 1e9, charged once per whole cohort; signed delta retained",
            "ratio": "median Scan adjusted rate / median alternative adjusted rate; whole paired process rounds resampled together",
            "scope": "Sequential seeded subscriber cohorts; not concurrent-reader scaling or request-latency distributions",
            "T2_rows_including_warmup": observed,
            "saved_warmup_rows": sum(sum(counts.values()) for counts in warmups.values()), "cohorts": cohorts,
            "paired_comparisons": comparisons}


def self_test():
    import copy
    row = {"cpu_ns": 100, "arm": "indexed/binheap", "config": {"market_seconds": 10, "R": 1000},
           "work": {"publish_window_market_seconds": 1800,
                    "publish_index_on_cpu_ns": 3000, "publish_index_off_cpu_ns": 1200}}
    assert math.isclose(metrics(row)["adjusted_cpu_per_market_second"], 11e-9)
    row["config"]["R"] = 1
    assert math.isclose(metrics(row)["adjusted_cpu_per_market_second"], 11e-9)
    row["arm"] = "scan"
    assert metrics(row)["charged_amortized_index_cpu_ns"] == 0
    assert math.isclose(metrics(row)["adjusted_cpu_per_market_second"], 10e-9)
    row["arm"] = "indexed/binheap"
    row["work"].update(publish_index_on_cpu_ns=1000, publish_index_off_cpu_ns=2800)
    assert metrics(row)["publish_index_delta_cpu_ns"] == -1800
    assert math.isclose(metrics(row)["adjusted_cpu_per_market_second"], 9e-9)
    fixtures = []
    names = ["scan"] + [f"{mode}/{kernel}" for mode in ("indexed", "auto")
                         for kernel in ("stdpq", "binheap", "quad", "loser")]
    for readers in (1, 10, 100, 1000):
        for cache in ("repeat-warm", "scratch-thrashed"):
            for rep in range(-1, 20):
                for name in names:
                    item = copy.deepcopy(row)
                    item.update(exp="T2", comparison_id=f"R{readers}-{cache}",
                                workload_id="fixture", cache=cache, arm=name,
                                rep=rep, warmup=rep == -1, status="ok", oracle_validated=True,
                                measurement_command_ok=True, process_round_id=f"fixture-R{readers}-{cache}-{rep}",
                                paired_round_id=f"fixture:{rep}", raw_path="fixture-only", out_count=readers,
                                cpu_ns=200 if name == "scan" else 100)
                    item["config"]["R"] = readers
                    item["work"].update(publish_index_on_cpu_ns=3000, publish_index_off_cpu_ns=1200)
                    fixtures.append(item)
    result = summarize(fixtures)
    assert len(result["cohorts"]) == 8
    assert len(result["paired_comparisons"]) == 64
    assert all(math.isclose(item["ratio"], 20 / 11) and math.isclose(item["ci95_low"], 20 / 11)
               and math.isclose(item["ci95_high"], 20 / 11) for item in result["paired_comparisons"])
    bad_cases = [fixtures[:-1], fixtures + [fixtures[-1]],
                 [item for item in fixtures if item["comparison_id"] != "R1000-scratch-thrashed"],
                 [item for item in fixtures if not (item["comparison_id"] == "R1-repeat-warm"
                    and item["warmup"] and item["arm"] == "scan")]]
    duplicate_warmup = copy.deepcopy(fixtures)
    duplicate_warmup[0]["arm"] = "indexed/binheap"
    bad_cases.append(duplicate_warmup)
    for case in bad_cases:
        try:
            summarize(case)
        except ValueError:
            pass
        else:
            raise AssertionError("incomplete/duplicate fixture accepted")
    print(json.dumps({"status": "passed", "checks": 14,
                      "coverage": "cohort-once, unequal durations, Scan exclusion, signed negative delta, paired CI, incomplete/duplicate-round/cohort/warm-up rejection; generated format fixtures only"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/derived/t2-adjusted-paired.json"))
    parser.add_argument("--seed", type=int, default=20191230)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.rows is None:
        parser.error("rows required")
    def rows():
        with args.rows.open("rb") as stream:
            for line in stream:
                if b'"T2"' in line:
                    yield json.loads(line)
    result = summarize(rows(), seed=args.seed)
    with args.rows.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result.update(input=str(args.rows), input_sha256=digest,
                  generated_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": "passed", "output": str(args.output),
                      "cohorts": len(result["cohorts"]), "comparisons": len(result["paired_comparisons"])}))


if __name__ == "__main__":
    main()
