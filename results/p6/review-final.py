"""Closeout review of actual coverage, statistics and rendered-data metadata."""
from collections import Counter, defaultdict
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
count = 0
failures = []


def check(condition, label):
    global count
    count += 1
    if not condition:
        failures.append(label)


def load(name):
    return json.loads((ROOT / name).read_text())


def sha(name):
    with (ROOT / name).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


plan = load("results/raw/P6/prepared-evaluation/plan.json")
expected = {f"real-C{c}-B1024" for c in (1073741824, 2147483648)}
expected |= {f"synth-P{p}-Z{z}-L{l}-S20191231" for p in (10, 1000, 100000)
             for z in (0.0, 0.8, 1.2) for l in (1, 16, 256)}
expected |= {f"memory-B{b}-A{a}" for b in (64, 256, 1024, 4096)
             for a in (34500000000000, 35100000000000, 36000000000000)}
check({w["id"] for w in plan["workloads"]} == expected, "independent approved41workload set")
for workload in plan["workloads"]:
    name = workload["id"]
    expected_requests = (21006 if name == "real-C1073741824-B1024" else
                         252 if name.startswith("real-") else
                         162 if name.startswith("synth-") else 2)
    check(workload["requests"] == expected_requests, "approved request count:" + name)
    check(sha(workload["path"]) == workload["sha256"], "prepared-case identity:" + name)
state = load("results/raw/P6/campaign-20261024/evaluation/state.json")
reps = defaultdict(list)
for item in state["completed_processes"]:
    reps[item["workload_id"]].append(item["rep"])
    check(item["returncode"] == 0 and item["measurement_command_ok"] is True
          and item["oracle_failures"] == 0, "accepted completed process:" + item["id"])
check(set(reps) == expected, "actual workload coverage")
for name, values in reps.items():
    check(len(values) == 21 and set(values) == set(range(-1, 20)), "saved warmup plus20rounds:" + name)

summary = load("results/derived/tip-summary.json")
expected_groups = {"M1": 451, "M1-touch": 450, "M2": 120, "M3": 8,
                   "T1": 1260, "T2": 72, "T3": 4374, "T5": 24}
check(dict(Counter(g["exp"] for g in summary["configurations"])) == expected_groups,
      "all declared configuration groups including preserved interruption")
metrics_checked = 0
for group in summary["configurations"]:
    check(group["n_measured"] == group["n_ok"] + group["n_non_ok"], "outcome conservation:" + group["config_id"])
    check(group["noise_observed_count"] + group["noise_unknown_count"] == group["n_measured"],
          "noise conservation:" + group["config_id"])
    for name, metric in group["metrics"].items():
        metrics_checked += 1
        ordered = [metric[k] for k in ("min", "q1", "median", "q3", "max")]
        check(all(math.isfinite(v) for v in ordered) and ordered == sorted(ordered),
              "finite ordered distribution:" + group["config_id"] + "/" + name)
        check(metric["bootstrap_resamples"] == 10000
              and metric["n"] + metric["missing_among_ok"] == group["n_ok"]
              and metric["min"] <= metric["ci95_low"] <= metric["median"] <= metric["ci95_high"] <= metric["max"],
              "sample/interval coverage:" + group["config_id"] + "/" + name)
pairs = summary["paired_comparisons"]
check(Counter((p["exp"], p["status"]) for p in pairs) ==
      Counter({("T1", "ok"): 1120, ("T2", "ok"): 64, ("T3", "ok"): 3672,
               ("T3", "incomplete_pairs"): 216}), "all paired outcomes including withheld cells")
for pair in pairs:
    if pair["status"] == "ok":
        check(pair["paired_rounds"] == 20 and pair["bootstrap_resamples"] == 10000
              and pair["bootstrap_unit"] == "whole_paired_round", "actual whole-round pair")
    else:
        check(pair["ratio"] is pair["ci95_low"] is pair["ci95_high"] is None,
              "unavailable comparison has no invented timing ratio")

figures = load("results/figures/p6-figures.json")
panels = figures["figure_facets"]["F12"]
check(len(panels) == 54, "all54 crossover strata")
available = unavailable = 0
paired = {(p["comparison_id"], p["denominator"]): p for p in pairs if p["exp"] == "T3"}
configs = {g["config_id"]: g for g in summary["configurations"]}
for panel in panels:
    positions = set()
    check(len(panel["points"]) == 72, "eight arms at each of nine actual cells")
    for point in panel["points"]:
        position = (point["x"], point["y"])
        check(position not in positions, "no arm marker overlap")
        positions.add(position)
        config = configs[point["config_id"]]
        pair = paired[(config["comparison_id"], point["arm"])]
        check(point["ratio"] == pair["ratio"], "plotted ratio equals exact saved comparison")
        available += point["ratio"] is not None
        unavailable += point["ratio"] is None
check((available, unavailable) == (3672, 216), "all successful and unavailable crossover points represented")
check(sha(summary["input"]) == summary["input_sha256"] == figures["input_sha256"],
      "actual raw-to-summary-to-figure identity")

record = {
    "status": "passed" if not failures else "failed",
    "at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "checks": count, "metric_summaries_reviewed": metrics_checked, "failures": failures,
    "delegated_review_completed_before_final_rendering": {
        "task": "/root/p6_gate_audit",
        "scope": "Independent source/matrix review, original auditor amendment and5364-file identity review,65 statistics/report checks and28 T5/noise-table checks reported in session messages before final presentation-only title positioning.",
        "limits": "The final rendering was inspected by the root, not represented as a later delegated review.",
    },
    "root_closeout_review": "Rechecks explicit approved workload coverage, all completed rounds, every numerical summary/pair and exact nonoverlapping crossover metadata. Final visual review covers F09,F12,F13 and title placement; prior accepted hot-source and raw-file integrity are separately recorded.",
    "numerical_source": {"path": "results/derived/tip-summary.json", "sha256": sha("results/derived/tip-summary.json")},
}
(ROOT / "results/p6/final-gate-review.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({"status": record["status"], "checks": count,
                  "metric_summaries": metrics_checked, "failures": failures[:10]}))
raise SystemExit(0 if not failures else 1)
