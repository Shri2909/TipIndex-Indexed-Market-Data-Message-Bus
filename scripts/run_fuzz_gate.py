#!/usr/bin/env python3
"""Run a restartable fuzz gate for >=1800 confirmed monotonic seconds.

Only child processes which exit zero and print all final libFuzzer statistics
contribute time. Each completed segment is atomically checkpointed. An
interrupted, unconfirmed segment contributes nothing, even if its log looks
complete. Resume requires the same binary, options, sanitizer environment and
corpus directory; corpus additions are retained across restarts.
"""

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


SCHEMA = 2
STAT_NAMES = ("number_of_executed_units", "average_exec_per_sec", "new_units_added",
              "slowest_unit_time_sec", "peak_rss_mb")
ENV_NAMES = ("ASAN_OPTIONS", "UBSAN_OPTIONS", "DEBUGINFOD_URLS", "TIPLOG_FUZZ_MODE",
             "TIPLOG_EXECUTION_CONTEXT")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def save_atomic(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def corpus_manifest(path):
    return {str(child.relative_to(path)): sha256(child)
            for child in sorted(path.rglob("*")) if child.is_file()}


def verify_corpus(path, expected):
    # Files at process startup are libFuzzer seeds. Interrupted segments may
    # add new files, but checkpointed seeds must survive unchanged.
    for name, digest in expected.items():
        file = path / name
        if not file.is_file() or sha256(file) != digest:
            raise ValueError(f"checkpointed corpus file changed or missing: {file}")


def final_stats(log):
    raw = log.read_text(errors="replace")
    values = {}
    for name in STAT_NAMES:
        found = re.findall(rf"^stat::{name}:\s+(\d+)\s*$", raw, re.MULTILINE)
        if len(found) != 1:
            raise ValueError(f"missing/duplicate final {name} in {log}")
        values[name] = int(found[0])
    if values["number_of_executed_units"] < 1 or "DONE" not in raw:
        raise ValueError(f"no completed fuzz execution in {log}")
    if re.search(r"ERROR: (AddressSanitizer|LeakSanitizer|libFuzzer)|runtime error:", raw):
        raise ValueError(f"sanitizer/fuzzer diagnostic in {log}")
    return values


def verify_completed(summary):
    elapsed = 0.0
    units = 0
    for segment in summary["attempts"]:
        if segment["status"] != "passed":
            if segment["status"] == "interrupted_unconfirmed":
                continue
            raise ValueError("failed gate cannot resume; investigate and regress failure first")
        log = Path(segment["log"])
        if segment["exit_code"] != 0 or sha256(log) != segment["log_sha256"]:
            raise ValueError(f"completed segment exit/log verification failed: {log}")
        if final_stats(log) != segment["final_stats"]:
            raise ValueError(f"completed segment statistics verification failed: {log}")
        elapsed += segment["monotonic_seconds"]
        units += segment["final_stats"]["number_of_executed_units"]
    if elapsed != summary["monotonic_seconds"] or units != summary["executed_units"]:
        raise ValueError("checkpoint totals do not match completed segments")


def run(args):
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    destination = Path("results") / args.phase
    artifacts = destination / "fuzz-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    args.corpus.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.setdefault("ASAN_OPTIONS", "detect_leaks=1:abort_on_error=1")
    environment.setdefault("UBSAN_OPTIONS", "print_stacktrace=1:halt_on_error=1")
    environment["DEBUGINFOD_URLS"] = ""
    if "detect_leaks=1" not in environment["ASAN_OPTIONS"] or "halt_on_error=1" not in environment["UBSAN_OPTIONS"]:
        raise ValueError("required sanitizer checks must remain enabled")
    configuration = {
        "phase": args.phase, "label": args.label,
        "binary": str(args.binary.resolve()), "binary_sha256": sha256(args.binary),
        "corpus": str(args.corpus.resolve()),
        "dictionary": str(args.dictionary.resolve()) if args.dictionary else None,
        "dictionary_sha256": sha256(args.dictionary) if args.dictionary else None,
        "cpu": args.cpu, "base_seed": args.seed, "segment_seconds": args.segment_seconds,
        "required_monotonic_seconds": args.seconds,
        "environment": {name: environment.get(name) for name in ENV_NAMES},
        "fixed_flags": ["-print_final_stats=1", "-max_len=65536", "-len_control=0",
                        "-rss_limit_mb=2048", "-timeout=10", "-print_funcs=0"],
        "runner_sha256": sha256(Path(__file__)),
    }
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    summary_path = args.resume or destination / f"{args.label}-gate-{stamp}.json"
    # Prevent accidental concurrent --resume of a single gate.
    with summary_path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.resume:
            summary = json.loads(summary_path.read_text())
            if summary.get("schema") != SCHEMA or summary["configuration"] != configuration:
                raise ValueError("resume binary/configuration/environment differs from checkpoint")
            verify_completed(summary)
            verify_corpus(args.corpus, summary["corpus_checkpoint"])
            if summary["status"] == "failed":
                raise ValueError("failed gate requires investigation, not automatic continuation")
            active = summary.pop("active_attempt", None)
            if active is not None:
                active["status"] = "interrupted_unconfirmed"
                active["accepted_monotonic_seconds"] = 0.0
                active["reason"] = "runner interrupted before confirmed child exit and atomic checkpoint"
                summary["attempts"].append(active)
            summary["resumptions"].append({"utc": utc_now(), "argv": sys.argv})
        else:
            summary = {
                "schema": SCHEMA, "status": "running", "started_utc": utc_now(),
                "configuration": configuration,
                "binary": str(args.binary), "binary_sha256": configuration["binary_sha256"],
                "required_monotonic_seconds": args.seconds, "monotonic_seconds": 0.0,
                "attempts": [], "executed_units": 0, "resumptions": [],
                "initial_argv": sys.argv, "environment": configuration["environment"],
                "corpus_checkpoint": corpus_manifest(args.corpus),
            }
        summary["status"] = "running"
        save_atomic(summary_path, summary)
        print(f"GATE: {summary_path}", flush=True)
        while summary["monotonic_seconds"] < args.seconds:
            if sha256(args.binary) != configuration["binary_sha256"]:
                raise ValueError("binary changed during fuzz gate")
            remaining = max(1, math.ceil(args.seconds - summary["monotonic_seconds"]))
            duration = min(args.segment_seconds, remaining)
            attempt = len(summary["attempts"]) + 1
            seed = (args.seed + attempt - 1) % (2**32 - 1) or 1
            log = summary_path.with_name(f"{summary_path.stem}-segment{attempt:03d}.log")
            argv = ["taskset", "-c", str(args.cpu), str(args.binary), str(args.corpus),
                    f"-max_total_time={duration}", f"-seed={seed}",
                    *configuration["fixed_flags"], f"-artifact_prefix={artifacts}/"]
            if args.dictionary:
                argv.append(f"-dict={args.dictionary}")
            active = {"number": attempt, "argv": argv, "seed": seed, "log": str(log),
                      "started_utc": utc_now(), "requested_seconds": duration}
            summary["active_attempt"] = active
            save_atomic(summary_path, summary)
            print(f"{args.label}: segment {attempt}, requested {duration}s, "
                  f"confirmed {summary['monotonic_seconds']:.3f}s, {log}", flush=True)
            start_wall, start_mono = time.time(), time.monotonic()
            with log.open("x") as output:
                result = subprocess.run(argv, stdout=output, stderr=subprocess.STDOUT, env=environment)
                output.flush()
                os.fsync(output.fileno())
            elapsed, wall = time.monotonic() - start_mono, time.time() - start_wall
            active.update({"exit_code": result.returncode, "monotonic_seconds": elapsed,
                           "wall_seconds": wall, "clock_discontinuity_seconds": wall - elapsed,
                           "finished_utc": utc_now(), "log_sha256": sha256(log)})
            try:
                if result.returncode != 0:
                    raise ValueError(f"child exited {result.returncode}")
                active["final_stats"] = final_stats(log)
            except ValueError as error:
                active.update({"status": "failed", "reason": str(error)})
                summary["status"] = "failed"
                summary["attempts"].append(active)
                del summary["active_attempt"]
                save_atomic(summary_path, summary)
                print(f"FAILED: {summary_path}: {error}", flush=True)
                return 1
            active["status"] = "passed"
            summary["attempts"].append(active)
            summary["monotonic_seconds"] += elapsed
            summary["executed_units"] += active["final_stats"]["number_of_executed_units"]
            summary["corpus_checkpoint"] = corpus_manifest(args.corpus)
            del summary["active_attempt"]
            save_atomic(summary_path, summary)
            print(f"{args.label}: checkpoint {summary['monotonic_seconds']:.3f}s; "
                  f"{summary['executed_units']} executions", flush=True)
        summary["status"] = "passed"
        summary["finished_utc"] = utc_now()
        save_atomic(summary_path, summary)
        print(f"PASSED: {summary_path}; {summary['monotonic_seconds']:.3f}s; "
              f"{summary['executed_units']} executions", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path)
    parser.add_argument("--cpu", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20191230)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--segment-seconds", type=int, default=120)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    if args.seconds < 1800:
        parser.error("phase gates require at least 1800 seconds")
    if not 1 <= args.segment_seconds <= 120:
        parser.error("segments must be between 1 and 120 seconds")
    try:
        return run(args)
    except (ValueError, OSError) as error:
        print(f"fuzz gate error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
