#!/usr/bin/env python3
"""Independently reconcile a completed P6 RC-3 run and current frozen identities."""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGURATIONS = {("scan", "stdpq")} | {(mode, kernel) for mode in ("indexed", "auto")
                                          for kernel in ("stdpq", "binheap", "quad", "loser")}
CASES = {"basket-success", "basket-expiry", "wide-success", "wide-expiry", "synthetic"}
LABELS = {"mode", "kernel", "effective_last_range_mode"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=Path("results/p6/rc3-summary.json"))
    parser.add_argument("--output", type=Path, default=Path("results/p6/rc3-final-verified.json"))
    args = parser.parse_args()
    summary_path = ROOT / args.summary
    summary = json.loads(summary_path.read_text())
    checks, failures = [], []

    def check(value, label):
        checks.append({"check": label, "status": "passed" if value else "failed"})
        if not value:
            failures.append(label)

    check(summary["status"] == "passed", "checker terminal status passed")
    check(summary["repeats_per_compiler"] >= 2, "at least two repeats per compiler")
    repeats = summary["repeats_per_compiler"]
    expected_count = len(CASES) * len(CONFIGURATIONS) * 2 * repeats
    check(summary["run_count"] == len(summary["runs"]) == expected_count, "exact functional child coverage")
    check(all(item["status"] == "passed" for item in summary["comparisons"]), "all checker equality records passed")
    check(sha(ROOT / summary["trace"]) == summary["trace_sha256"], "actual trace identity")
    for name, digest in summary["source_sha256"].items():
        check((ROOT / name).is_file() and sha(ROOT / name) == digest, "current frozen source:" + name)
    for build in summary["builds"].values():
        for name, digest in build["binaries"].items():
            check(sha(ROOT / build["directory"] / name) == digest, "current binary:" + build["directory"] + "/" + name)
    grouped, across, identities, child_hashes = defaultdict(list), defaultdict(list), set(), {}
    for name in summary["runs"]:
        path = ROOT / name
        child = json.loads(path.read_text())
        child_hashes[name] = sha(path)
        label = f"child{child['number']:03d}"
        check(child["exit_code"] == 0 and child["stderr"] == "", label + ":successful child without diagnostics")
        parsed = json.loads(child["stdout"])
        check(parsed == child["parsed_output"], label + ":raw stdout matches saved parsed value")
        case, mode, kernel = child["case"], child["mode"], child["kernel"]
        identity = (case, mode, kernel, child["compiler"], child["repeat"])
        check(identity not in identities, label + ":unique case/compiler/repeat")
        identities.add(identity)
        check(case in CASES and (mode, kernel) in CONFIGURATIONS and child["compiler"] in {"gcc", "clang"}, label + ":declared case/configuration/compiler")
        check(child["repeat"] in range(1, repeats + 1), label + ":declared repetition")
        check(child["argv"][:3] == ["taskset", "-c", str(summary["cpu"])], label + ":recorded affinity command")
        if case == "synthetic":
            check(parsed["status"] == "passed" and parsed["operations"] == 25000, label + ":synthetic operation coverage")
            canonical = {key: value for key, value in parsed.items() if key != "elapsed_monotonic_seconds"}
        else:
            check(parsed["published"] == 10000 and parsed["delivered"] > 0, label + ":real trace count/prefix")
            if case.endswith("success"):
                check(parsed["outcome"] == "done" and "error" not in parsed
                      and parsed["checkpoint"]["after_seq"] == 10000, label + ":success checkpoint")
            else:
                check(parsed["outcome"] == "error" and parsed["error"]["kind"] == "FellBehind"
                      and parsed["error"]["last_delivered"] > 0
                      and set(parsed["error"]) == {"kind", "requested_after", "last_delivered", "oldest_retained"}, label + ":explicit expiry and delivered prefix")
            canonical = parsed
            across[case].append({key: value for key, value in parsed.items() if key not in LABELS})
        grouped[(case, mode, kernel)].append(canonical)
    check(len(grouped) == len(CASES) * len(CONFIGURATIONS), "all case/configuration groups present")
    for key, values in grouped.items():
        check(len(values) == 2 * repeats and all(value == values[0] for value in values), "independent repeated GCC/Clang equality:" + "/".join(key))
    for key, values in across.items():
        check(all(value == values[0] for value in values), "independent across-configuration observable equality:" + key)
    output = {"schema": 1, "status": "passed" if not failures else "failed",
              "verified_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "summary": str(args.summary), "summary_sha256": sha(summary_path),
              "verifier_sha256": sha(Path(__file__)), "child_count": len(summary["runs"]),
              "checker_equality_count": len(summary["comparisons"]),
              "independently_verified_groups": len(grouped), "child_file_sha256": child_hashes,
              "checks": checks, "failures": failures}
    (ROOT / args.output).write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({key: output[key] for key in ("status", "child_count", "checker_equality_count", "independently_verified_groups", "failures")}))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
