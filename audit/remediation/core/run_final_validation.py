#!/usr/bin/env python3
"""Run functional remediation gates; all new evidence stays under audit/.

This is not a quiet-host performance campaign. At most two tested processes
run concurrently. Existing results and seed corpora are never modified.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent / "final-validation"
PAIRS = [("scan", "stdpq")] + [
    (mode, kernel) for mode in ("indexed", "auto")
    for kernel in ("stdpq", "binheap", "quad", "loser")
]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    partial.replace(path)


def sources():
    selected = {ROOT / "CMakeLists.txt", ROOT / "CMakePresets.json"}
    for directory in ("src", "tools", "tests", "cmake", "py/tiplog_py", "py/tests"):
        selected.update(path for path in (ROOT / directory).rglob("*")
                        if path.is_file() and path.suffix in {
                            ".cpp", ".hpp", ".h", ".c", ".py", ".cmake",
                            ".json", ".yml", ".yaml", ".toml"})
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(selected)}


def execute(job):
    folder = OUTPUT / job["id"]
    folder.mkdir()
    command = job["command"]
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                       UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=1")
    environment.update(job.get("environment", {}))
    record = dict(job, started_utc=now(), binary_sha256_before=sha(Path(command[0])),
                  sanitizer_environment={key: environment[key] for key in
                                         ("ASAN_OPTIONS", "UBSAN_OPTIONS")})
    save(folder / "invocation.json", record)
    start = time.monotonic()
    with (folder / "stdout.log").open("wb") as stdout, (folder / "stderr.log").open("wb") as stderr:
        try:
            process = subprocess.run(command, cwd=OUTPUT, env=environment,
                                     stdout=stdout, stderr=stderr, timeout=3600)
            record["exit_status"] = process.returncode
        except subprocess.TimeoutExpired:
            record.update(exit_status=None, timeout_seconds=3600)
    record.update(finished_utc=now(), elapsed_monotonic_seconds=time.monotonic() - start,
                  binary_sha256_after=sha(Path(command[0])))
    record["binary_unchanged"] = record["binary_sha256_before"] == record["binary_sha256_after"]
    if job["kind"] == "differential" and record["exit_status"] == 0:
        try:
            result = json.loads((folder / "stdout.log").read_text())
            record["result"] = result
            record["passed"] = (result["status"] == "passed" and
                                result["seeds"] == job["seeds"] and
                                result["operations"] == job["seeds"] * 10000 and
                                record["binary_unchanged"])
        except (KeyError, ValueError) as exc:
            record.update(passed=False, result_error=str(exc))
    elif job["kind"] == "fuzz":
        log = (folder / "stderr.log").read_text(errors="replace")
        record["passed"] = (record["exit_status"] == 0 and record["binary_unchanged"] and
                            "stat::number_of_executed_units: 10000" in log)
        record["final_stats"] = [line for line in log.splitlines() if line.startswith("stat::")]
    else:
        record["passed"] = False
    save(folder / "result.json", record)
    print(json.dumps({key: record.get(key) for key in
                      ("id", "passed", "exit_status", "elapsed_monotonic_seconds")}), flush=True)
    return record


def main():
    OUTPUT.mkdir(exist_ok=False)
    initial = sources()
    save(OUTPUT / "source-hashes-before.json", initial)
    save(OUTPUT / "runner-identity.json", {"path": str(Path(__file__).relative_to(ROOT)),
                                         "sha256": sha(Path(__file__)), "python": sys.version,
                                         "pid": os.getpid(), "started_utc": now(),
                                         "maximum_tested_children": 2,
                                         "performance_claim": False})
    jobs = []
    for preset, seeds in (("release", 1000), ("asan-ubsan", 200)):
        binary = ROOT / "build" / preset / "tiplog_differential"
        for mode, kernel in PAIRS:
            jobs.append({"id": f"{preset}-{mode}-{kernel}", "kind": "differential",
                         "preset": preset, "seeds": seeds, "mode": mode, "kernel": kernel,
                         "command": [str(binary), "--seed-base", "1", "--seeds", str(seeds),
                                     "--operations", "10000", "--mode", mode, "--kernel", kernel]})
    for target, source, environment in (
            ("fuzz_trace_reader", "trace_reader", {}),
            ("fuzz_itch_walker", "itch_walker", {}),
            ("fuzz_engine_ops", "ops_integrated", {"TIPLOG_FUZZ_MODE": "all"})):
        corpus = OUTPUT / (target + "-corpus")
        shutil.copytree(ROOT / "tests/fuzz/corpus" / source, corpus)
        manifest = {str(path.relative_to(corpus)): sha(path)
                    for path in sorted(corpus.rglob("*")) if path.is_file()}
        save(OUTPUT / (target + "-seed-hashes.json"), manifest)
        artifacts = OUTPUT / (target + "-artifacts")
        artifacts.mkdir()
        jobs.append({"id": target, "kind": "fuzz", "environment": environment,
                     "seed_corpus_source": "tests/fuzz/corpus/" + source,
                     "command": [str(ROOT / "build/fuzz" / target), str(corpus),
                                 "-runs=10000", "-seed=1", "-max_len=65536",
                                 "-detect_leaks=1", "-print_final_stats=1",
                                 "-artifact_prefix=" + str(artifacts) + "/"]})
    save(OUTPUT / "planned-jobs.json", jobs)
    completed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(execute, job) for job in jobs]
        for future in concurrent.futures.as_completed(pending):
            completed.append(future.result())
            save(OUTPUT / "progress.json", {"completed": completed, "total_jobs": len(jobs)})
    final = sources()
    save(OUTPUT / "source-hashes-after.json", final)
    groups = {}
    for preset in ("release", "asan-ubsan"):
        records = [item for item in completed if item.get("preset") == preset]
        digests = {item.get("result", {}).get("digest_fnv1a64") for item in records}
        groups[preset] = {"pairs": len(records), "all_passed": all(item["passed"] for item in records),
                          "mode_independent_digest_equal": len(digests) == 1 and None not in digests,
                          "digest_values": sorted(value for value in digests if value is not None),
                          "operations": sum(item.get("result", {}).get("operations", 0) for item in records),
                          "seeds_per_pair": 1000 if preset == "release" else 200}
    summary = {"finished_utc": now(), "source_unchanged": initial == final,
               "groups": groups, "jobs": sorted(completed, key=lambda item: item["id"]),
               "maximum_tested_children": 2, "performance_claim": False,
               "cross_preset_digest_comparison": "Different seed counts; compare within each preset cohort."}
    summary["passed"] = (initial == final and len(completed) == len(jobs) and
                         all(item["passed"] for item in completed) and
                         all(group["mode_independent_digest_equal"] for group in groups.values()))
    save(OUTPUT / "summary.json", summary)
    print(json.dumps({"passed": summary["passed"], "groups": groups,
                      "report": str(OUTPUT / "summary.json")}), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
