#!/usr/bin/env python3
"""Independently verify saved P6 F3 terminal evidence without executing fuzzing."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
STATS = ("number_of_executed_units", "average_exec_per_sec", "new_units_added",
         "slowest_unit_time_sec", "peak_rss_mb")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=Path, default=Path(
        "results/p6/F3-instrumented-segmented-gate-20261019T013136.964232Z.json"))
    parser.add_argument("--freeze", type=Path, default=Path("results/p6/fuzz-source-freeze.json"))
    parser.add_argument("--output", type=Path, default=Path("results/p6/fuzz-gate-verified.json"))
    args = parser.parse_args()
    gate_path, freeze_path = ROOT / args.gate, ROOT / args.freeze
    gate, freeze = json.loads(gate_path.read_text()), json.loads(freeze_path.read_text())
    failures, checks = [], []

    def check(condition: bool, label: str) -> None:
        checks.append({"check": label, "status": "passed" if condition else "failed"})
        if not condition:
            failures.append(label)

    check(gate["schema"] == 2 and gate["status"] == "passed", "terminal schema/status")
    check("active_attempt" not in gate, "no unconfirmed active segment")
    check(gate["required_monotonic_seconds"] >= 1800, "required gate duration >=1800 seconds")
    check(gate["monotonic_seconds"] >= gate["required_monotonic_seconds"], "confirmed monotonic duration")
    config = gate["configuration"]
    check(config["phase"] == "p6" and config["cpu"] == 6, "phase and CPU identity")
    check(config["environment"] == gate["environment"], "sanitizer environment identity")
    env = gate["environment"]
    check("detect_leaks=1" in env["ASAN_OPTIONS"] and "abort_on_error=1" in env["ASAN_OPTIONS"], "ASan and leak checking enabled")
    check("halt_on_error=1" in env["UBSAN_OPTIONS"], "UBSan halt enabled")
    check(env["TIPLOG_FUZZ_MODE"] == "all", "all replay mode/kernel coverage requested")
    check(env["TIPLOG_EXECUTION_CONTEXT"] == "outside-sandbox", "sanitizer execution context recorded")
    binary = ROOT / gate["binary"]
    check(binary.is_file() and sha(binary) == gate["binary_sha256"] == config["binary_sha256"], "current binary matches frozen binary")
    check(sha(ROOT / "scripts/run_fuzz_gate.py") == config["runner_sha256"], "gate runner hash")
    for name, digest in freeze["files"].items():
        path = ROOT / name
        check(path.is_file() and sha(path) == digest, f"frozen source:{name}")
    elapsed, units, peak, segments = 0.0, 0, 0, []
    for number, segment in enumerate(gate["attempts"], start=1):
        label = f"segment{number:03d}"
        check(segment["number"] == number and segment["status"] == "passed" and segment["exit_code"] == 0, f"{label}:terminal successful child")
        log = ROOT / segment["log"]
        check(log.is_file() and sha(log) == segment["log_sha256"], f"{label}:log hash")
        raw = log.read_text(errors="replace")
        parsed = {}
        for field in STATS:
            values = re.findall(rf"^stat::{field}:\s+(\d+)\s*$", raw, re.MULTILINE)
            check(len(values) == 1, f"{label}:one final {field}")
            if len(values) == 1:
                parsed[field] = int(values[0])
        check(parsed == segment["final_stats"], f"{label}:independent final stats reconciliation")
        check(bool(re.search(r"^#\d+\s+DONE\b", raw, re.MULTILINE)), f"{label}:completed DONE marker")
        check(not re.search(r"ERROR: (?:AddressSanitizer|LeakSanitizer|libFuzzer)|runtime error:", raw), f"{label}:no sanitizer/fuzzer error")
        argv = segment["argv"]
        check(argv[:4] == ["taskset", "-c", "6", gate["binary"]], f"{label}:pinned binary argv")
        check(all(flag in argv for flag in config["fixed_flags"]), f"{label}:all fixed fuzz flags")
        check(f"-seed={segment['seed']}" in argv and segment["seed"] == config["base_seed"] + number - 1, f"{label}:seed schedule")
        check(segment["monotonic_seconds"] > 0 and math.isfinite(segment["monotonic_seconds"]), f"{label}:positive monotonic duration")
        check(abs(segment["wall_seconds"] - segment["monotonic_seconds"] - segment["clock_discontinuity_seconds"]) < 1e-8, f"{label}:clock bookkeeping")
        elapsed += segment["monotonic_seconds"]
        units += parsed.get("number_of_executed_units", 0)
        peak = max(peak, parsed.get("peak_rss_mb", 0))
        segments.append({"number": number, "log": segment["log"], "log_sha256": segment["log_sha256"], "monotonic_seconds": segment["monotonic_seconds"], **parsed})
    check(math.isclose(elapsed, gate["monotonic_seconds"], rel_tol=0, abs_tol=1e-9), "independent monotonic sum")
    check(units == gate["executed_units"] and units > 0, "independent execution count sum")
    corpus = Path(config["corpus"])
    current = {str(p.relative_to(corpus)): sha(p) for p in sorted(corpus.rglob("*")) if p.is_file()}
    check(current == gate["corpus_checkpoint"], "all final corpus names and hashes exactly preserved")
    artifacts = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "results/p6/fuzz-artifacts").rglob("*") if p.is_file())
    check(not artifacts, "no saved crash/timeout/OOM artifacts")
    output = {"schema": 1, "status": "passed" if not failures else "failed",
              "verified_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "gate": str(args.gate), "gate_sha256": sha(gate_path),
              "freeze": str(args.freeze), "freeze_sha256": sha(freeze_path),
              "verifier": str(Path(__file__).relative_to(ROOT)), "verifier_sha256": sha(Path(__file__)),
              "binary": gate["binary"], "binary_sha256": gate["binary_sha256"],
              "confirmed_monotonic_seconds": elapsed, "executed_units": units,
              "completed_segments": len(segments), "peak_rss_mb": peak,
              "frozen_source_count": len(freeze["files"]), "corpus_count": len(current),
              "artifact_files": artifacts, "segments": segments, "checks": checks,
              "failures": failures}
    destination = ROOT / args.output
    destination.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: output[k] for k in ("status", "confirmed_monotonic_seconds", "executed_units", "completed_segments", "peak_rss_mb", "frozen_source_count", "corpus_count", "failures")}))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
