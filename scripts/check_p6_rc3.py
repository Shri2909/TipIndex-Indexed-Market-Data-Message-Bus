#!/usr/bin/env python3
"""P6 RC-3: repeated, outcome-aware deterministic GCC/Clang functional checks.

This runs correctness checks, not a timing or performance experiment. Every
child argv, JSON output, stderr and exit status is retained. Runtime durations
from the synthetic diagnostic are excluded only from equality comparison.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parent.parent
CONFIGURATIONS = [("scan", "stdpq")] + [
    (mode, kernel)
    for mode in ("indexed", "auto")
    for kernel in ("stdpq", "binheap", "quad", "loser")
]
MODE_LABELS = {"mode", "kernel", "effective_last_range_mode"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def source_manifest():
    # Freeze the core + independent reference + two exercised executables.
    # Concurrent untimed bench-tool work has no linkage into these binaries.
    paths = [ROOT / "CMakeLists.txt", ROOT / "CMakePresets.json"]
    for directory in ("src", "tools/tiplog_sim", "tools/tiplog_differential",
                      "tests/differential", "tests/ref"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    paths.extend(path for path in (ROOT / "cmake").glob("*.cmake")
                 if path.name != "p6_bench.cmake")
    paths.append(Path(__file__).resolve())
    return {str(path.relative_to(ROOT)): sha256(path) for path in sorted(set(paths))}


def broad_manifest():
    paths = []
    for directory in ("src", "tools", "tests/differential", "tests/ref", "cmake"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    return {str(path.relative_to(ROOT)): sha256(path) for path in sorted(set(paths))}


def capture(argv):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {argv!r}: {result.stderr}")
    return {"argv": argv, "stdout": result.stdout, "stderr": result.stderr,
            "exit_code": result.returncode}


def build_manifest(directory):
    cache = (directory / "CMakeCache.txt").read_text()
    compiler = next(line.split("=", 1)[1] for line in cache.splitlines()
                    if line.startswith("CMAKE_CXX_COMPILER:"))
    commands = json.loads((directory / "compile_commands.json").read_text())
    selected = [entry for entry in commands if
                any(fragment in entry["file"] for fragment in
                    ("tiplog_sim/main.cpp", "tiplog_differential/main.cpp",
                     "/src/tiplog/", "/tests/ref/", "differential/campaign.cpp"))]
    return {"directory": str(directory.relative_to(ROOT)),
            "compiler": capture([compiler, "--version"]),
            "cmake_cache_sha256": sha256(directory / "CMakeCache.txt"),
            "compile_commands_sha256": sha256(directory / "compile_commands.json"),
            "relevant_compile_commands": selected,
            "binaries": {name: sha256(directory / name) for name in
                         ("tiplog_sim", "tiplog_differential")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcc", type=Path, default=Path("build/release"))
    parser.add_argument("--clang", type=Path, default=Path("build/clang-release"))
    parser.add_argument("--trace", type=Path,
                        default=Path("data/traces/itch_20191230_0930_1000_spec.mdt"))
    parser.add_argument("--cpu", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("RC-3 requires at least two repeated runs per compiler")
    os.chdir(ROOT)
    identifier = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = ROOT / f"results/p6/rc3-runs-{identifier}"
    destination.mkdir(parents=True, exist_ok=True)
    summary_path = ROOT / f"results/p6/rc3-summary-{identifier}.json"
    sources = source_manifest()
    git = capture([str(ROOT / "scripts/git.sh"), "rev-parse", "HEAD"])
    dirty = capture([str(ROOT / "scripts/git.sh"), "status", "--porcelain"])
    summary = {
        "status": "running", "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": "RC-3 functional reproducibility; no performance claims",
        "git_commit": git["stdout"].strip(), "git_dirty": bool(dirty["stdout"]),
        "source_sha256": sources, "broad_sources_at_start": broad_manifest(),
        "source_scope": "Core, independent reference, sim/differential and core build definitions; unrelated bench tool excluded. Exact tested binary hashes frozen before/after.",
        "trace": str(args.trace),
        "trace_sha256": sha256(args.trace), "repeats_per_compiler": args.repeats,
        "cpu": args.cpu, "configurations": CONFIGURATIONS,
        "comparisons": [], "runs": [],
        "comparison_rules": {
            "same_configuration_repeat_and_compiler": "all simulation JSON fields",
            "simulation_across_configurations": "all fields except explicit mode/kernel labels",
            "simulation_label_fields_excluded_across_configurations": sorted(MODE_LABELS),
            "differential_repeat_and_compiler": "all fields except elapsed_monotonic_seconds",
            "outcome_rule": "done must have checkpoint and no error; expiry must retain full FellBehind prefix",
        },
    }
    builds = {"gcc": args.gcc.resolve(), "clang": args.clang.resolve()}
    summary["builds"] = {label: build_manifest(path) for label, path in builds.items()}
    save(summary_path, summary)
    run_number = 0

    def run(binary, argv, case, compiler, mode, kernel, repeat):
        nonlocal run_number
        run_number += 1
        command = ["taskset", "-c", str(args.cpu), str(binary), *argv,
                   "--mode", mode, "--kernel", kernel]
        started = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        record = {"number": run_number, "case": case, "compiler": compiler,
                  "mode": mode, "kernel": kernel, "repeat": repeat,
                  "argv": command, "exit_code": result.returncode,
                  "stdout": result.stdout, "stderr": result.stderr,
                  "execution_bookkeeping_seconds": time.monotonic() - started}
        output_path = destination / f"{run_number:03d}-{case}-{compiler}-{mode}-{kernel}-r{repeat}.json"
        save(output_path, record)
        summary["runs"].append(str(output_path.relative_to(ROOT)))
        if result.returncode or result.stderr:
            raise AssertionError(f"child failed or wrote diagnostics: {output_path}")
        value = json.loads(result.stdout)
        record["parsed_output"] = value
        save(output_path, record)
        return value

    def compare(left, right, label):
        if left != right:
            raise AssertionError(f"deterministic output mismatch: {label}")
        summary["comparisons"].append({"check": label, "status": "passed"})

    scenarios = (
        ("basket-success", "done", ["--subtree", "itch/AAPL", "--subtree", "itch/MSFT",
          "--ring-bytes", "1048576", "--max-record-bytes", "524288",
          "--budget", "7", "--consume-every", "3", "--pause", "30:10", "--jitter-budget"]),
        ("basket-expiry", "error", ["--subtree", "itch/AAPL", "--subtree", "itch/MSFT",
          "--ring-bytes", "4096", "--max-record-bytes", "2048",
          "--budget", "2", "--consume-every", "1", "--pause", "2000:300"]),
        ("wide-success", "done", ["--subtree", "itch", "--ring-bytes", "1048576",
          "--max-record-bytes", "524288", "--budget", "17", "--consume-every", "3",
          "--pause", "30:10", "--jitter-budget"]),
        ("wide-expiry", "error", ["--subtree", "itch", "--ring-bytes", "4096",
          "--max-record-bytes", "2048", "--budget", "1", "--consume-every", "5",
          "--pause", "10:200"]),
    )
    try:
        for case, outcome, options in scenarios:
            across_configuration = None
            for mode, kernel in CONFIGURATIONS:
                reference = None
                for compiler, directory in builds.items():
                    for repeat in range(1, args.repeats + 1):
                        argv = ["--trace", str(args.trace), "--max-records", "10000",
                                "--seed", "20191230", "--pool-blocks", "16384",
                                "--block-entries", "64", *options]
                        value = run(directory / "tiplog_sim", argv, case, compiler,
                                    mode, kernel, repeat)
                        assert value["published"] == 10000
                        assert value["outcome"] == outcome
                        assert value["reader"] == "tail"
                        assert value["pressure_data_evicted"] == 0
                        assert value["pressure_bytes_evicted"] == 0
                        if outcome == "done":
                            assert "error" not in value and value["delivered"] > 0
                            assert value["checkpoint"]["after_seq"] == 10000
                        else:
                            assert value["error"]["kind"] == "FellBehind"
                            assert value["delivered"] > 0
                            assert value["error"]["last_delivered"] > 0
                            assert set(value["error"]) == {
                                "kind", "requested_after", "last_delivered", "oldest_retained"}
                        if case.startswith("wide"):
                            assert value["effective_last_range_mode"] == "scan"
                        elif case == "basket-success" and mode == "indexed":
                            assert value["effective_last_range_mode"] == "indexed"
                        if reference is None:
                            reference = value
                        else:
                            compare(reference, value,
                                    f"{case}/{mode}/{kernel}/{compiler}/repeat{repeat}")
                canonical = {key: value for key, value in reference.items()
                             if key not in MODE_LABELS}
                if across_configuration is None:
                    across_configuration = canonical
                else:
                    compare(across_configuration, canonical,
                            f"{case}/all-observable-fields/{mode}/{kernel}")
            print(f"RC-3 real trace {case}: all repeated GCC/Clang configurations passed", flush=True)
            save(summary_path, summary)

        for mode, kernel in CONFIGURATIONS:
            reference = None
            for compiler, directory in builds.items():
                for repeat in range(1, args.repeats + 1):
                    value = run(directory / "tiplog_differential",
                                ["--seed-base", "20191230", "--seeds", "5", "--operations", "5000"],
                                "synthetic", compiler, mode, kernel, repeat)
                    assert value["status"] == "passed" and value["operations"] == 25000
                    assert value["delivered"] > 0
                    canonical = {key: value for key, value in value.items()
                                 if key != "elapsed_monotonic_seconds"}
                    if reference is None:
                        reference = canonical
                    else:
                        compare(reference, canonical,
                                f"synthetic/{mode}/{kernel}/{compiler}/repeat{repeat}")
            print(f"RC-3 synthetic {mode}/{kernel}: repeated GCC/Clang outputs passed", flush=True)
            save(summary_path, summary)

        compare(sources, source_manifest(), "production source identity before/after all runs")
        for label, directory in builds.items():
            compare(summary["builds"][label]["binaries"],
                    {name: sha256(directory / name) for name in ("tiplog_sim", "tiplog_differential")},
                    f"{label} binary identity before/after all runs")
        summary["status"] = "passed"
    except Exception as error:
        summary["status"] = "failed"
        summary["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        summary["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        summary["run_count"] = run_number
        save(summary_path, summary)
        save(ROOT / "results/p6/rc3-summary.json", summary)
    print(f"RC-3 passed: {run_number} child runs, {len(summary['comparisons'])} equalities", flush=True)


if __name__ == "__main__":
    main()
