#!/usr/bin/env python3
"""P0 environment diagnostics; all machine settings are read only.

The taskset/perf/setarch children are short capability checks, not benchmarks.
Missing files, unavailable commands and denied probes remain explicit in JSON.
Only the standard library is required; stdout contains exactly one document.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
ERRORS: dict[str, str] = {}


def read(path: Path | str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        ERRORS[str(path)] = str(exc)
        return None


def read_json(path: Path) -> object | None:
    raw = read(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        ERRORS[str(path)] = str(exc)
        return None


def run(argv: list[str], timeout: float = 15) -> dict[str, object]:
    executable = shutil.which(argv[0])
    result: dict[str, object] = {
        "argv": argv,
        "cwd": str(ROOT),
        "executable": executable,
        "resolved_executable": str(Path(executable).resolve()) if executable else None,
        "returncode": None,
        "stdout": None,
        "stderr": None,
        "error": None,
    }
    try:
        child = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            env={**os.environ, "LC_ALL": "C"}, check=False,
        )
        result.update(returncode=child.returncode, stdout=child.stdout, stderr=child.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
    return result


def cpulist(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    result: set[int] = set()
    try:
        for item in raw.split(","):
            ends = item.split("-")
            result.update(range(int(ends[0]), int(ends[-1]) + 1))
        return sorted(result)
    except ValueError:
        ERRORS[f"cpulist:{raw}"] = "Unrecognized CPU list"
        return None


def key_values(raw: str | None) -> dict[str, str] | None:
    if raw is None:
        return None
    return {k.strip(): v.strip() for line in raw.splitlines()
            if ":" in line for k, v in [line.split(":", 1)]}


def build_info() -> dict[str, object]:
    caches: dict[str, object] = {}
    for path in sorted((ROOT / "build").glob("*/CMakeCache.txt")):
        raw = read(path)
        values = {}
        for line in (raw or "").splitlines():
            if line.startswith(("CMAKE_CXX_", "CMAKE_C_COMPILER:", "CMAKE_BUILD_TYPE:",
                                "CMAKE_GENERATOR:", "TIPLOG_")) and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        caches[str(path.relative_to(ROOT))] = values
    flags = {}
    for path in sorted((ROOT / "build").glob("*/CMakeFiles/*/flags.make")):
        # Generated flags include target options not present in CMakeCache.txt.
        flags[str(path.relative_to(ROOT))] = read(path)
    return {
        "presets": read_json(ROOT / "CMakePresets.json"),
        "cmake_caches": caches,
        "target_flags": flags,
        "environment_flags": {key: os.environ.get(key) for key in ("CC", "CXX", "CFLAGS", "CXXFLAGS", "LDFLAGS")},
    }


def git_info() -> dict[str, object]:
    # The .git directory belongs to the host and must never be initialized or changed.
    metadata = ROOT / ".tiplog-git"
    base = ["git", "--no-optional-locks", f"--git-dir={metadata}", f"--work-tree={ROOT}"]
    sha = run(base + ["rev-parse", "--verify", "HEAD"])
    status = run(base + ["status", "--porcelain=v1", "--untracked-files=normal"])
    return {
        "metadata": str(metadata),
        "managed_metadata_preserved": str(ROOT / ".git"),
        "head": sha,
        "status": status,
        "sha": str(sha["stdout"]).strip() if sha["returncode"] == 0 else None,
        "dirty": bool(status["stdout"]) if status["returncode"] == 0 else None,
        "unborn_head_allowed_at_bootstrap": sha["returncode"] != 0 and status["returncode"] == 0,
    }


PIN_DIAGNOSTIC = r'''
import ctypes, json, os, resource, time
from pathlib import Path
cpu = int(__import__("sys").argv[1])
errors = {}
def frequency():
    try:
        return int(Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq").read_text())
    except (OSError, ValueError) as exc:
        errors["frequency"] = str(exc)
        return None
libc = ctypes.CDLL(None, use_errno=True)
def current_cpu():
    try:
        value = libc.sched_getcpu()
        if value < 0:
            raise OSError(ctypes.get_errno(), "sched_getcpu failed")
        return value
    except (AttributeError, OSError) as exc:
        errors["sched_getcpu"] = str(exc)
        return None
before = frequency()
start_cpu = current_cpu()
start_usage = resource.getrusage(resource.RUSAGE_SELF)
start = time.perf_counter_ns()
checksum = sum(range(4096))
elapsed = time.perf_counter_ns() - start
end_usage = resource.getrusage(resource.RUSAGE_SELF)
end_cpu = current_cpu()
after = frequency()
print(json.dumps({"affinity": sorted(os.sched_getaffinity(0)), "cpu_start": start_cpu,
 "cpu_end": end_cpu, "frequency_before_khz": before, "frequency_after_khz": after,
 "diagnostic_only_not_benchmark": True, "checksum": checksum,
 "wall_ns": elapsed, "user_seconds": end_usage.ru_utime - start_usage.ru_utime,
 "system_seconds": end_usage.ru_stime - start_usage.ru_stime, "errors": errors}))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", type=int, default=2, help="CPU for a short taskset diagnostic (default: 2)")
    parser.add_argument("--preset", help="Label an existing build preset; does not configure or build it")
    args = parser.parse_args()
    if args.cpu < 0:
        parser.error("--cpu must be nonnegative")

    cpu_root = Path("/sys/devices/system/cpu")
    online = cpulist(read(cpu_root / "online"))
    topology = {}
    for cpu in online or []:
        base = cpu_root / f"cpu{cpu}"
        topology[str(cpu)] = {
            "physical_package_id": read(base / "topology/physical_package_id"),
            "core_id": read(base / "topology/core_id"),
            "thread_siblings_list": read(base / "topology/thread_siblings_list"),
            "core_type": read(base / "topology/core_type"),
            "scaling_governor": read(base / "cpufreq/scaling_governor"),
            "scaling_driver": read(base / "cpufreq/scaling_driver"),
            "cpuinfo_max_freq_khz": read(base / "cpufreq/cpuinfo_max_freq"),
        }
    pmus = {}
    for pmu in sorted(Path("/sys/bus/event_source/devices").glob("*")):
        pmus[pmu.name] = {"type": read(pmu / "type")}
        if (pmu / "cpus").exists():
            pmus[pmu.name]["cpus"] = read(pmu / "cpus")
        if pmu.name in ("cpu_core", "cpu_atom"):
            pmus[pmu.name]["events"] = {event.name: read(event) for event in sorted((pmu / "events").glob("*"))}
    core_cpus = cpulist(pmus.get("cpu_core", {}).get("cpus"))
    atom_cpus = cpulist(pmus.get("cpu_atom", {}).get("cpus"))
    siblings = cpulist(topology.get(str(args.cpu), {}).get("thread_siblings_list"))

    pin = run(["taskset", "-c", str(args.cpu), sys.executable, "-c", PIN_DIAGNOSTIC, str(args.cpu)])
    pin_details = None
    if pin["returncode"] == 0:
        try:
            pin_details = json.loads(str(pin["stdout"]))
        except json.JSONDecodeError as exc:
            ERRORS["pin_diagnostic.stdout"] = str(exc)

    events = ["cpu_core/cycles/u", "cpu_core/instructions/u", "cpu_core/branch-misses/u",
              "cpu_core/L1-dcache-load-misses/u", "cpu_core/LLC-load-misses/u"]
    event_lists = {event: run(["perf", "list", "--details", event]) for event in events}
    probes = {event: run(["perf", "stat", "--no-scale", "-x", ";", "-e", event,
                          "--", "taskset", "-c", str(args.cpu), "/usr/bin/true"])
              for event in (events[0], events[1], "task-clock")}
    aslr_probe = run(["setarch", platform.machine(), "-R", sys.executable,
                      "-c", "import json; from pathlib import Path; "
                      "print(json.dumps({'child_started': True, "
                      "'personality_hex': Path('/proc/self/personality').read_text().strip()}))"])

    supplies = {}
    for supply in sorted(Path("/sys/class/power_supply").glob("*")):
        supplies[supply.name] = {name: read(supply / name) for name in
                                 ("type", "online", "status", "capacity") if (supply / name).exists()}
    ac_values = [entry.get("online") for entry in supplies.values()
                 if entry.get("type") in ("Mains", "USB", "USB_C", "USB_PD")]
    ac_online = any(value == "1" for value in ac_values) if ac_values else None
    thermals = {zone.name: {"type": read(zone / "type"), "temp_millidegrees_c": read(zone / "temp")}
                for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*"))}
    disk = shutil.disk_usage(ROOT)
    cpuinfo = read("/proc/cpuinfo")
    models = sorted({line.split(":", 1)[1].strip() for line in (cpuinfo or "").splitlines()
                     if line.startswith("model name")})
    master = ROOT / "MASTER_PROJECT_PROMPT.md"
    try:
        master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    except OSError as exc:
        ERRORS[str(master)] = str(exc)
        master_sha = None
    status = key_values(read("/proc/self/status"))
    tools = {name: run([name, "--version"]) for name in
             ("gcc", "g++", "clang", "clang++", "cmake", "make", "perf", "valgrind", "taskset", "setarch", "git")}
    result = {
        "schema_version": 1,
        "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "phase": "P0.4",
        "capture_invocation": [str(ROOT / "scripts/env_capture.sh"), *sys.argv[1:]],
        "selected_preset": args.preset,
        "machine_settings_changed": False,
        "kernel": {"uname": list(platform.uname()), "os_release": read("/etc/os-release")},
        "cpu": {"models": models, "online": online, "topology": topology, "pmus": pmus,
                "lscpu": run(["lscpu", "--json"])},
        "controls": {"no_turbo": read(cpu_root / "intel_pstate/no_turbo"),
                     "smt_active": read(cpu_root / "smt/active"),
                     "smt_control": read(cpu_root / "smt/control"),
                     "perf_event_paranoid": read("/proc/sys/kernel/perf_event_paranoid"),
                     "aslr_randomize_va_space": read("/proc/sys/kernel/randomize_va_space"),
                     "per_process_aslr_probe": aslr_probe,
                     "supplies": supplies, "ac_online": ac_online, "thermals": thermals},
        "affinity": {"capture_process": sorted(os.sched_getaffinity(0)), "requested_cpu": args.cpu,
                     "cpu_is_core_pmu_member": args.cpu in core_cpus if core_cpus is not None else None,
                     "cpu_is_atom_pmu_member": args.cpu in atom_cpus if atom_cpus is not None else None,
                     "smt_siblings": siblings, "pin_diagnostic": pin, "pin_details": pin_details,
                     "pin_verified": bool(pin_details is not None and pin_details.get("affinity") == [args.cpu]
                                          and pin_details.get("cpu_start") == args.cpu
                                          and pin_details.get("cpu_end") == args.cpu),
                     "smt_sibling_idle_verified": False,
                     "limitation": "Affinity does not isolate shared caches, package power, thermals, or sibling activity."},
        "profiling": {"decision": "DEC-2=no: no privileged settings changes; time/getrusage fallback",
                      "perf_list": event_lists, "availability_probes": probes,
                      "hardware_counter_measurement_selected": False,
                      "counter_values": None, "time_enabled": None, "time_running": None, "scaling": None,
                      "control_probe": {"status": "not_run", "reason": "Fallback selected; no successful counter collection required for P0."},
                      "fallback": {"timing": ["wall_clock", "getrusage_user_seconds", "getrusage_system_seconds"],
                                   "cachegrind": "planned reduced configurations in later experiments; instruction/cache counts must be labeled simulated; not run in P0",
                                   "hardware_counter_claims": False},
                      "limitation": "perf-list names or exit status alone do not demonstrate usable counters. Probes are diagnostics, not performance results."},
        "tools": tools,
        "python": {"executable": sys.executable, "resolved_executable": str(Path(sys.executable).resolve()),
                   "version": sys.version, "prefix": sys.prefix, "base_prefix": sys.base_prefix},
        "resources": {"meminfo": key_values(read("/proc/meminfo")), "disk_path": str(ROOT),
                      "disk_total_bytes": disk.total, "disk_used_bytes": disk.used, "disk_free_bytes": disk.free,
                      "load_average": list(os.getloadavg())},
        "process_security_context": {key: (status or {}).get(key) for key in
                                     ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs", "Seccomp")},
        "build": build_info(),
        "git": git_info(),
        "master_project_prompt_sha256": master_sha,
        "read_errors": ERRORS,
        "limitations": ["Point-in-time environment observation; P6 still requires AC power and a pilot.",
                        "No SMT offlining, frequency/governor/turbo/ASLR sysctl changes or privilege elevation.",
                        "Frequency samples bracket a short plumbing diagnostic, not a benchmark or stable-frequency proof."],
    }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
