#!/usr/bin/env python3
"""Run the isolated, limited P5 microbenchmark pilot; never build or run fuzzing.

The default only prints the plan. --run additionally requires a saved root-agent
quiescence declaration. No settings are changed; denied ASLR/counter probes stay
in the fresh environment capture. Raw files and failed attempts are preserved.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
CPU = 2
SEED = 20191230
FLAGS = [
    "--benchmark_repetitions=15",
    "--benchmark_enable_random_interleaving=true",
    "--benchmark_min_warmup_time=0.2",
    "--benchmark_min_time=0.5s",
    "--benchmark_report_aggregates_only=false",
    "--benchmark_display_aggregates_only=false",
    "--benchmark_out_format=json",
    "--benchmark_color=false",
]
DECLARATIONS = (
    "fuzz_finished", "conversion_finished", "tests_finished", "builds_finished",
    "other_agents_quiescent",
)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def save(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            result.update(block)
    return result.hexdigest()


def identity(path: Path) -> dict[str, object]:
    display = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    return {"path": str(display), "bytes": path.stat().st_size,
            "sha256": sha(path)}


def text(path: str | Path) -> str | None:
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def frequency() -> int | None:
    value = text(f"/sys/devices/system/cpu/cpu{CPU}/cpufreq/scaling_cur_freq")
    return int(value) if value and value.isdigit() else None


def power() -> dict[str, object]:
    supplies = {}
    for path in sorted(Path("/sys/class/power_supply").glob("*")):
        supplies[path.name] = {field: text(path / field) for field in
                               ("type", "online", "status", "capacity")}
    values = [item["online"] for item in supplies.values()
              if item["type"] in ("Mains", "USB", "USB_C", "USB_PD")]
    return {"supplies": supplies, "ac_online": any(v == "1" for v in values)
            if values else None}


def sibling_ticks() -> list[int] | None:
    for line in (text("/proc/stat") or "").splitlines():
        if line.startswith("cpu3 "):
            return [int(word) for word in line.split()[1:9]]
    return None


def observation() -> dict[str, object]:
    return {"at_utc": now(), "monotonic_ns": time.monotonic_ns(),
            "cpu2_frequency_khz": frequency(), "power": power(),
            "sibling_cpu3_ticks": sibling_ticks(),
            "load_average": list(os.getloadavg())}


def proc_scan() -> dict[str, object]:
    """Observe visible processes; this cannot prove host-wide isolation."""
    offenders, errors = [], []
    names = {"ctest", "pytest", "tiplog_differential", "tiplog_walk", "trace_check",
             "tiplog_sim", "cmake", "make", "gmake", "cc1plus", "cc1", "clang",
             "clang++", "gcc", "g++", "ld", "ld.lld", "merge_bench", "publish_bench"}
    ancestors = {os.getpid()}
    cursor = os.getppid()
    while cursor and cursor not in ancestors:
        ancestors.add(cursor)
        status = text(f"/proc/{cursor}/status") or ""
        parent = next((line.split()[1] for line in status.splitlines()
                       if line.startswith("PPid:")), "0")
        cursor = int(parent)
    for directory in Path("/proc").glob("[0-9]*"):
        pid = int(directory.name)
        if pid in ancestors:
            continue
        try:
            raw = (directory / "cmdline").read_bytes()
            args = [arg.decode(errors="replace") for arg in raw.split(b"\0") if arg]
            if not args:
                continue
            name = Path(args[0]).name
            python_work = name.startswith("python") and any(
                item in {"tiplog_py.itch", "tiplog_py.itch.cli", "pytest"}
                or Path(item).name in {"run_fuzz_gate.py", "check_all.py", "run_check.py"}
                for item in args[1:])
            if name in names or name.startswith("fuzz_") or python_work:
                offenders.append({"pid": pid, "argv": args})
        except FileNotFoundError:
            pass  # A process exiting during enumeration is ordinary.
        except (OSError, ValueError) as exc:
            errors.append({"pid": pid, "error": str(exc)})
    return {"at_utc": now(), "pid_namespace": os.readlink("/proc/self/ns/pid"),
            "proc1_comm": text("/proc/1/comm"), "offenders": offenders,
            "read_errors": errors, "excluded_runner_ancestors": sorted(ancestors),
            "limit": "Visible process snapshot plus saved operator declaration; no host-wide isolation claim."}


def require_quiet(path: Path) -> dict[str, object]:
    declaration = json.loads(path.read_text())
    if declaration.get("status") != "passed" or any(
            declaration.get(key) is not True for key in DECLARATIONS):
        raise RuntimeError("quiescence declaration is missing a required true condition")
    scan = proc_scan()
    if scan["offenders"]:
        raise RuntimeError("competing authorized work is still visible: " +
                           json.dumps(scan["offenders"]))
    return {"declaration": identity(path), "conditions": declaration, "visible_processes": scan}


def command_record(argv: list[str], stdout: Path, stderr: Path,
                   env: dict[str, str] | None = None) -> dict[str, object]:
    start = time.monotonic_ns()
    with stdout.open("w") as out, stderr.open("w") as err:
        child = subprocess.run(argv, cwd=ROOT, stdout=out, stderr=err,
                               env=env, check=False)
    return {"argv": argv, "cwd": str(ROOT), "returncode": child.returncode,
            "wall_ns": time.monotonic_ns() - start,
            "stdout": identity(stdout), "stderr": identity(stderr)}


def git_info() -> dict[str, object]:
    def run(*args: str) -> str:
        child = subprocess.run([str(ROOT / "scripts/git.sh"), "--no-optional-locks", *args],
                               cwd=ROOT, capture_output=True, text=True, check=True)
        return child.stdout.strip()
    head = run("rev-parse", "--verify", "HEAD")
    if len(head) != 40:
        raise RuntimeError("an actual Git commit is required before the pilot")
    status = run("status", "--porcelain=v1", "--untracked-files=normal")
    return {"sha": head, "dirty": bool(status), "status_porcelain": status,
            "metadata": ".tiplog-git", "managed_git_preserved": True}


def provenance() -> dict[str, object]:
    manifest = json.loads((ROOT / "data/manifest.json").read_text())
    source = identity(ROOT / manifest["path"])
    if source["sha256"] != manifest["sha256"]:
        raise RuntimeError("source gzip hash differs from accepted data manifest")
    inputs = [source, identity(ROOT / "data/manifest.json")]
    for name in ("spec", "flat"):
        meta = ROOT / f"data/traces/itch_20191230_0930_1000_{name}.mdt.meta.json"
        description = json.loads(meta.read_text())
        trace = identity(ROOT / description["trace"]["path"])
        if trace["sha256"] != description["trace"]["sha256"]:
            raise RuntimeError(f"{name} trace hash differs from accepted metadata")
        if description["source"]["sha256"] != source["sha256"]:
            raise RuntimeError("trace and source gzip identities differ")
        inputs.extend([trace, identity(meta)])
    inputs.extend(identity(ROOT / name) for name in (
        "configs/m2_payload_mix.csv", "configs/m2_payload_mix.meta.json",
        "results/data/itch_20191230_counts.json"))
    mix = json.loads((ROOT / "configs/m2_payload_mix.meta.json").read_text())
    for field, filename in (("source_counts_sha256", mix["source_counts"]),
                            ("mix_sha256", mix["mix_file"]),
                            ("spec_table_source_sha256", "py/tiplog_py/itch/protocol.py")):
        if sha(ROOT / filename) != mix[field]:
            raise RuntimeError(f"empirical payload mix identity mismatch: {field}")
    if mix["source_gzip_sha256"] != source["sha256"]:
        raise RuntimeError("empirical payload mix and source gzip identities differ")
    paths = [ROOT / name for name in ("CMakeLists.txt", "CMakePresets.json",
                                      "py/requirements.txt")]
    for directory in ("src", "tools", "bench", "scripts", "cmake"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    paths.extend((ROOT / "build/release").glob("**/flags.make"))
    paths.extend(ROOT / name for name in ("build/release/CMakeCache.txt",
                                         "build/release/compile_commands.json"))
    return {"git": git_info(), "preset": "release", "cpu": CPU, "seed": SEED,
            "inputs": inputs, "source_files": [identity(path) for path in sorted(set(paths))],
            "binaries": [identity(ROOT / f"build/release/{name}")
                         for name in ("merge_bench", "publish_bench")],
            "benchmark_dependency": {"version": "1.9.5", "revision":
                "192ef10025eb2c4cdd392bc502f0c852196baa48"},
            "input_scope": "Synthetic M1 and fixed64-byte M2; Nasdaq identities retain provenance, not a real-trace replay claim."}


def plan() -> list[tuple[str, list[str], int]]:
    return [
        ("M1", [str(ROOT / "build/release/merge_bench"), "--profile=pilot",
                "--quad-padding-both", f"--seed={SEED}"], 15),
        *[(f"M2-B{block}", [str(ROOT / "build/release/publish_bench"),
            "--payload", "64", "--partitions", "100", "--block-entries", str(block),
            "--distribution", "uniform", "--seed", str(SEED)], 2)
          for block in (256, 1024)],
    ]


def settle(directory: Path, declaration: Path) -> dict[str, object]:
    started = time.monotonic_ns()
    samples = []
    while True:
        elapsed = (time.monotonic_ns() - started) / 1e9
        sample = observation()
        samples.append(sample)
        save(directory / "settling.json", {"started_monotonic_ns": started,
             "elapsed_seconds": elapsed, "samples": samples, "complete": elapsed >= 60})
        if sample["power"]["ac_online"] is not True:
            raise RuntimeError("AC power is required during settling and measurement")
        if elapsed >= 60:
            break
        print(json.dumps({"block": directory.name, "state": "settling",
                          "elapsed_seconds": round(elapsed, 2)}), flush=True)
        time.sleep(min(10.0, 60.0 - elapsed))
    quiet = require_quiet(declaration)
    save(directory / "quiescence-before.json", quiet)
    return {"elapsed_seconds": (time.monotonic_ns() - started) / 1e9,
            "minimum_seconds": 60, "clock": "monotonic"}


def usage_delta(before: resource.struct_rusage,
                after: resource.struct_rusage) -> dict[str, object]:
    return {"user_ns": round((after.ru_utime - before.ru_utime) * 1e9),
            "system_ns": round((after.ru_stime - before.ru_stime) * 1e9),
            "minor_faults": after.ru_minflt - before.ru_minflt,
            "major_faults": after.ru_majflt - before.ru_majflt,
            "voluntary_context_switches": after.ru_nvcsw - before.ru_nvcsw,
            "involuntary_context_switches": after.ru_nivcsw - before.ru_nivcsw,
            "scope": "Whole single child process including setup, warm-up, calibration, repetitions and teardown; not hot-loop CPU time."}


def run_block(directory: Path, argv: list[str], aslr_disabled: bool,
              declaration: Path) -> dict[str, object]:
    inherited_benchmark_environment = {key: value for key, value in os.environ.items()
                                       if key.startswith("BENCHMARK_")}
    env = {**{key: value for key, value in os.environ.items()
              if not key.startswith("BENCHMARK_")}, "LC_ALL": "C", "TIPLOG_BENCH_INVOCATIONS":
           str(directory / "invocations.jsonl"), "TIPLOG_BENCH_INPUTS":
           str(directory / "inputs.jsonl")}
    executable = ["setarch", platform.machine(), "-R"] if aslr_disabled else []
    full = ["taskset", "-c", str(CPU), *executable, *argv, *FLAGS,
            f"--benchmark_out={directory / 'gbench.json'}"]
    settle_result = settle(directory, declaration)
    record = {"argv": full, "cwd": str(ROOT), "started_at_utc": now(),
              "removed_inherited_benchmark_environment": inherited_benchmark_environment,
              "environment_overrides": {key: env[key] for key in
                  ("LC_ALL", "TIPLOG_BENCH_INVOCATIONS", "TIPLOG_BENCH_INPUTS")},
              "status": "running", "settling": settle_result, "before": observation()}
    record["provenance_reference"] = "../provenance.json"
    record["environment_reference"] = "../environment.json"
    if record["before"]["cpu2_frequency_khz"] is None:
        raise RuntimeError("mandatory CPU2 frequency observation is unavailable")
    save(directory / "command.json", record)
    before_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic_ns()
    samples = []
    power_failed = False
    interrupted = None
    with (directory / "stdout.log").open("w") as out, (directory / "stderr.log").open("w") as err:
        try:
            child = subprocess.Popen(full, cwd=ROOT, stdout=out, stderr=err, env=env)
        except OSError as exc:
            record.update(status="failed", returncode=None, error=str(exc),
                          finished_at_utc=now(), wall_ns=time.monotonic_ns() - start,
                          after=observation())
            save(directory / "command.json", record)
            return record
        try:
            while True:
                try:
                    child.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    sample = observation()
                    samples.append(sample)
                    if sample["power"]["ac_online"] is not True:
                        power_failed = True
                        child.terminate()
                    print(json.dumps({"block": directory.name, "state": "running",
                                      "elapsed_seconds": round((time.monotonic_ns() - start) / 1e9, 1)}), flush=True)
        except BaseException as exc:
            interrupted = f"{type(exc).__name__}: {exc}"
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        returncode = child.wait()
    after_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    record.update(returncode=returncode, finished_at_utc=now(),
                  wall_ns=time.monotonic_ns() - start, after=observation(),
                  child_usage=usage_delta(before_usage, after_usage),
                  power_failed=power_failed, runtime_observations=samples,
                  interrupted=interrupted,
                  status="ok" if returncode == 0 and not power_failed and not interrupted else "failed")
    if record["after"]["power"]["ac_online"] is not True:
        record.update(power_failed=True, status="failed")
    if record["after"]["cpu2_frequency_khz"] is None:
        record.update(status="failed", frequency_error="mandatory final sample unavailable")
    for name in ("stdout.log", "stderr.log", "gbench.json", "invocations.jsonl", "inputs.jsonl"):
        if (directory / name).exists():
            record[name] = identity(directory / name)
    save(directory / "command.json", record)
    return record


def summarize(directory: Path, expected_cases: int) -> dict[str, object]:
    errors, profiles = [], {}
    raw = json.loads((directory / "gbench.json").read_text())
    for row in raw.get("benchmarks", []):
        if row.get("run_type", "iteration") != "iteration":
            continue
        name = row.get("run_name", row["name"])
        group = profiles.setdefault(name, {"rows": [], "non_ok_count": 0})
        group["rows"].append(row)
        if row.get("error_occurred") or row.get("skipped"):
            group["non_ok_count"] += 1
    if len(profiles) != expected_cases:
        errors.append(f"expected {expected_cases} cases, observed {len(profiles)}")
    groups = []
    for name, value in profiles.items():
        rows = value["rows"]
        if len(rows) != 15:
            errors.append(f"{name}: expected 15 individual repetitions, observed {len(rows)}")
        indices = [row.get("repetition_index") for row in rows]
        if sorted(index for index in indices if isinstance(index, int)) != list(range(15)):
            errors.append(f"{name}: repetition indices are missing or duplicated")
        cpu, wall = [], []
        for row in rows:
            denominator = row.get("outputs_per_iteration", row.get("publishes_per_iteration"))
            if row.get("time_unit") != "ns" or not denominator or denominator <= 0:
                errors.append(f"{name}: missing ns units or positive items per iteration")
                continue
            if not row.get("error_occurred"):
                cpu.append(row["cpu_time"] / denominator)
                wall.append(row["real_time"] / denominator)
        groups.append({"profile": name, "n": len(rows), "non_ok_count": value["non_ok_count"],
                       "median_cpu_ns_per_item": statistics.median(cpu) if cpu else None,
                       "median_wall_ns_per_item": statistics.median(wall) if wall else None})
    invocations = [json.loads(line) for line in
                   (directory / "invocations.jsonl").read_text().splitlines() if line]
    for invocation in invocations:
        if invocation.get("cpu_start") != CPU or invocation.get("cpu_end") != CPU:
            errors.append(f"invocation {invocation.get('invocation')}: CPU pin mismatch")
        if invocation.get("failed"):
            errors.append(f"invocation {invocation.get('invocation')}: benchmark reported failure")
        if any(invocation.get(key) is None for key in
               ("cpu2_frequency_start_khz", "cpu2_frequency_end_khz")):
            errors.append(f"invocation {invocation.get('invocation')}: missing frequency sample")
    if not invocations:
        errors.append("invocation log is empty")
    if any(group["non_ok_count"] for group in groups):
        errors.append("Google Benchmark reported non-ok repetitions")
    return {"status": "passed" if not errors else "failed", "errors": errors,
            "groups": groups, "invocations": len(invocations),
            "raw_json": identity(directory / "gbench.json"),
            "raw_invocations": identity(directory / "invocations.jsonl"),
            "scope": "Limited P5 pilot medians only; no confidence interval, kernel-winner or calibrated-Auto claim. Full matrix and P6.2 remain unrun."}


def frequency_flags(root: Path, blocks: list[dict[str, object]]) -> dict[str, object]:
    samples = []
    for block in blocks:
        command_path = root / block["label"] / "command.json"
        if command_path.exists():
            command = json.loads(command_path.read_text())
            for boundary in ("before", "after"):
                value = command.get(boundary, {}).get("cpu2_frequency_khz")
                if value is not None:
                    samples.append({"block": block["label"], "invocation": None,
                                    "boundary": boundary, "frequency_khz": value})
        path = root / block["label"] / "invocations.jsonl"
        if not path.exists():
            continue
        for row in map(json.loads, path.read_text().splitlines()):
            for boundary in ("start", "end"):
                value = row.get(f"cpu2_frequency_{boundary}_khz")
                if value is not None:
                    samples.append({"block": block["label"], "invocation": row["invocation"],
                                    "boundary": boundary, "frequency_khz": value})
    median = statistics.median(item["frequency_khz"] for item in samples) if samples else None
    for sample in samples:
        sample["deviation_fraction"] = abs(sample["frequency_khz"] / median - 1) if median else None
        sample["flagged_over_10_percent"] = sample["deviation_fraction"] > 0.10 if median else None
    result = {"session_median_khz": median, "samples": samples,
              "flagged_samples": sum(item["flagged_over_10_percent"] is True for item in samples),
              "policy": "All flagged samples and associated invocations/repetitions are retained. Endpoints do not establish constant clock frequency or isolation."}
    save(root / "frequency-flags.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Execute after all other work stops")
    parser.add_argument("--quiescence-record", type=Path)
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({"status": "plan_only_no_benchmarks_run", "blocks": plan(),
                          "flags": FLAGS, "settle_seconds_per_block": 60,
                          "required_quiescence_keys": ["status=passed", *DECLARATIONS]}, indent=2))
        return 0
    if args.quiescence_record is None:
        parser.error("--run requires --quiescence-record")
    declaration = args.quiescence_record.resolve()
    latest = ROOT / "results/p5/pilot-latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ROOT / "build/p5/pilot.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    head = git_info()
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_id = f"{timestamp}_{head['sha'][:12]}{'-dirty' if head['dirty'] else ''}_{platform.node()}"
    directory = ROOT / "results/raw/P5" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    state = {"schema_version": 1, "run_id": run_id, "status": "preflight",
             "started_at_utc": now(), "output_directory": str(directory.relative_to(ROOT)),
             "blocks": [], "command": sys.argv, "machine_settings_changed": False,
             "hardware_counter_claims": False, "cachegrind": "separate reduced simulated diagnostic required; not executed by this timing runner"}
    def checkpoint() -> None:
        save(directory / "session.json", state)
        save(latest, state)
    checkpoint()
    try:
        original_affinity = sorted(os.sched_getaffinity(0))
        observer_affinity = [cpu for cpu in original_affinity if cpu not in (2, 3)]
        if not observer_affinity:
            raise RuntimeError("runner requires an observer CPU outside benchmark CPU2 and sibling3")
        os.sched_setaffinity(0, observer_affinity)
        state["observer_affinity"] = {"inherited": original_affinity,
                                      "selected": sorted(os.sched_getaffinity(0)),
                                      "scope": "Runner only; benchmark child explicitly re-pins to CPU2."}
        state["quiescence"] = require_quiet(declaration)
        # Large input hashes, all source inspection and capability probes precede settling.
        state["provenance"] = provenance()
        save(directory / "provenance.json", state["provenance"])
        capture = command_record([str(ROOT / "scripts/env_capture.sh"), "--cpu", "2", "--preset", "release"],
                                 directory / "environment.json", directory / "environment.stderr.log")
        state["environment_capture"] = capture
        if capture["returncode"]:
            raise RuntimeError("fresh environment capture failed")
        environment = json.loads((directory / "environment.json").read_text())
        if environment["controls"]["ac_online"] is not True:
            raise RuntimeError("fresh environment does not establish AC power")
        if not environment["affinity"]["pin_verified"] or not environment["affinity"]["cpu_is_core_pmu_member"]:
            raise RuntimeError("fresh child affinity/P-core diagnostic failed")
        aslr = environment["controls"]["per_process_aslr_probe"]
        disable_aslr = aslr["returncode"] == 0
        state["aslr_regime"] = "per-process disabled" if disable_aslr else "host ASLR retained after failed per-process probe"
        state["status"] = "running"
        checkpoint()
        for label, argv, expected_cases in plan():
            block_dir = directory / label
            block_dir.mkdir()
            block = {"label": label, "status": "running", "expected_cases": expected_cases}
            state["blocks"].append(block)
            checkpoint()
            block["command"] = run_block(block_dir, argv, disable_aslr, declaration)
            block["summary"] = summarize(block_dir, expected_cases)
            block["status"] = "passed" if block["command"]["status"] == "ok" and block["summary"]["status"] == "passed" else "failed"
            save(block_dir / "summary.json", block["summary"])
            checkpoint()
            if block["status"] != "passed":
                raise RuntimeError(f"{label} pilot failed; all raw outcomes retained")
        state["frequency_flags"] = frequency_flags(directory, state["blocks"])
        # Changes to results are expected; code/binary changes invalidate this session.
        frozen = state["provenance"]["source_files"] + state["provenance"]["binaries"]
        changed = [item["path"] for item in frozen if sha(ROOT / item["path"]) != item["sha256"]]
        state["source_binary_changes"] = changed
        state["git_after"] = git_info()
        if changed:
            raise RuntimeError("source or binary changed during pilot: " + ", ".join(changed))
        state["quiescence_after"] = require_quiet(declaration)
        state["status"] = "passed"
    except BaseException as exc:  # Preserve failed/interrupted sessions and all their rows.
        state["status"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"
        if state["blocks"] and state["blocks"][-1]["status"] == "running":
            state["blocks"][-1].update(status="failed", error=state["error"])
        try:
            state["frequency_flags"] = frequency_flags(directory, state["blocks"])
        except Exception as summary_error:
            state["frequency_summary_error"] = str(summary_error)
    state["finished_at_utc"] = now()
    checkpoint()
    print(json.dumps({"status": state["status"], "session": str(directory / "session.json"),
                      "error": state.get("error")}), flush=True)
    return 0 if state["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
