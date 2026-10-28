"""Comparison helpers for audit reproductions. Each subcommand prints a JSON
verdict and exits nonzero on mismatch."""
import glob
import json
import os
import sys


def load(path):
    with open(path) as stream:
        return json.load(stream)


def cc2(directory, recorded):
    rows = {os.path.basename(p)[:-5]: load(p) for p in sorted(glob.glob(os.path.join(directory, "cc2-*.json")))}
    record = {f"cc2-{r['mode']}-{r['kernel']}": r["result"] for r in load(recorded)["rows"] if r["preset"] == "release"}
    fields = ["seeds", "operations", "publications", "rejected_publications", "opens", "batches", "delivered",
              "history_expired_opens", "fell_behind_batches", "empty_specs_rejected", "digest_fnv1a64",
              "indexed_execution_batches", "scan_execution_batches"]
    out = {"configs": len(rows), "per_config": {}}
    ok = len(rows) == 9
    for name, row in rows.items():
        same = all(row.get(f) == record[name].get(f) for f in fields)
        ok &= same and row["status"] == "passed"
        out["per_config"][name] = {"status": row["status"], "matches_recorded": same,
                                   "digest": row["digest_fnv1a64"], "delivered": row["delivered"],
                                   "batches": row["batches"],
                                   "execution_batches": row["indexed_execution_batches"] + row["scan_execution_batches"],
                                   "history_expired_opens": row["history_expired_opens"], "opens": row["opens"],
                                   "elapsed_s": row["elapsed_monotonic_seconds"]}
    any_row = next(iter(rows.values()))
    out["coverage_profile"] = {
        "operations": any_row["operations"], "batches": any_row["batches"],
        "execution_batch_fraction": (any_row["indexed_execution_batches"] + any_row["scan_execution_batches"]) / any_row["batches"],
        "history_expired_open_fraction": any_row["history_expired_opens"] / any_row["opens"],
        "delivered_per_operation": any_row["delivered"] / any_row["operations"]}
    out["unique_digests"] = sorted({r["digest_fnv1a64"] for r in rows.values()})
    out["verdict"] = "PASS" if ok and len(out["unique_digests"]) == 1 else "FAIL"
    return out


def counts(a, b):
    def by(d, key):
        return {str(k): (v["count"] if isinstance(v, dict) else v) for k, v in d[key].items()}
    return {"messages": [a["message_count"], b["message_count"]],
            "types_equal": by(a, "by_type") == by(b, "by_type"),
            "locates_equal": by(a, "by_locate") == by(b, "by_locate"),
            "locates": len(a["by_locate"]),
            "verdict": "PASS" if a["message_count"] == b["message_count"] and by(a, "by_type") == by(b, "by_type")
            and by(a, "by_locate") == by(b, "by_locate") else "FAIL"}


def rc3(directory):
    rows = {os.path.basename(p): load(p) for p in glob.glob(os.path.join(directory, "*.json"))}
    keys = ["published", "delivered", "replay_digest_fnv1a64", "outcome", "head_seq", "tail_seq", "checkpoint",
            "error", "effective_last_range_mode", "publication_digest_fnv1a64"]
    out = {"pairs": {}}
    ok = True
    for name, row in sorted(rows.items()):
        if name.startswith("release-clang"):
            continue
        other = rows["release-clang" + name[len("release"):]]
        same = all(row.get(k) == other.get(k) for k in keys)
        ok &= same
        out["pairs"][name] = {"gcc_equals_clang": same, "outcome": row["outcome"], "delivered": row["delivered"],
                              "effective_mode": row["effective_last_range_mode"],
                              "error": (row.get("error") or {}).get("kind")}
    gcc = {n: r for n, r in rows.items() if not n.startswith("release-clang")}
    for suffix in ("narrow.json", "expiry.json"):
        group = [r for n, r in gcc.items() if n.endswith(suffix)]
        identity = {(r["replay_digest_fnv1a64"], r["delivered"], json.dumps(r.get("error"), sort_keys=True)) for r in group}
        out[f"modes_identical_{suffix[:-5]}"] = len(identity) == 1
        ok &= len(identity) == 1
    out["verdict"] = "PASS" if ok else "FAIL"
    return out


def cc5(new, recorded):
    keys = ["status", "seed", "requested_instances", "completed_instances", "maximum_nodes", "maximum_classes",
            "exact_count_comparisons", "at_most_comparisons", "reconstructed_layouts_checked",
            "random_layouts_checked", "nodes", "zero_volume_nodes", "empty_trees", "consumer_classes"]
    a, b = load(new), load(recorded)
    differing = [k for k in keys if a.get(k) != b.get(k)]
    return {"new": {k: a.get(k) for k in keys}, "differing_from_recorded": differing,
            "verdict": "PASS" if a.get("status") == "passed" and not differing else "FAIL"}


def p7sum(path):
    totals, statuses, rows = {}, {}, 0
    with open(path) as stream:
        for line in stream:
            row = json.loads(line)
            rows += 1
            key = row["method"]
            statuses.setdefault(key, {}).setdefault(row["status"], 0)
            statuses[key][row["status"]] += 1
            if row["status"] == "feasible" and row["objective"] is not None:
                totals[key] = totals.get(key, 0) + int(row["objective"])
    out = {"rows": rows, "objective_totals_feasible_rows": totals, "statuses": statuses}
    if "base" in totals and "dp" in totals:
        out["dp_vs_base_percent"] = round(100.0 * (totals["dp"] - totals["base"]) / totals["base"], 2)
    if "km-min" in totals and "dp" in totals:
        out["kmmin_vs_dp_percent"] = round(100.0 * (totals["km-min"] - totals["dp"]) / totals["dp"], 2)
    out["verdict"] = "PASS" if all(set(v) == {"feasible"} for v in statuses.values()) else "FAIL"
    return out


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "cc2":
        result = cc2(sys.argv[2], sys.argv[3])
    elif command == "counts":
        result = counts(load(sys.argv[2]), load(sys.argv[3]))
    elif command == "cc5":
        result = cc5(sys.argv[2], sys.argv[3])
    elif command == "p7sum":
        result = p7sum(sys.argv[2])
    elif command == "rc3":
        result = rc3(sys.argv[2])
    else:
        raise SystemExit("unknown command")
    print(json.dumps(result, indent=1))
    raise SystemExit(0 if result["verdict"] == "PASS" else 1)
