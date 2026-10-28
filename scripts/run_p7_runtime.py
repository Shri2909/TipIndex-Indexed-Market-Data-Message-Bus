#!/usr/bin/env python3
"""Execute the separately authorized controlled P7 DP runtime supplement.

Preparation creates this runner only. Do not invoke it until the original cost
campaign has passed and the runtime protocol/build checks are complete. It uses
the existing 900 synthetic cases, never changes the solver, and keeps all caps
and non-solved outcomes. See results/p7/runtime-method.md.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
from fractions import Fraction
import gc
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
LIMIT_KEYS = ("dp_max_classes", "enum_max_edges", "max_states", "max_work", "time_limit_ms")
EXPECTED = {"configuration_count": 900, "warmup_rounds": 1, "measured_rounds": 10,
            "shuffle_seed": 20191230, "settle_seconds": 60, "cpu": 2, "observer_cpu": 6}
COST_FIELDS = ("scale", "objective", "stores", "read_bytes", "useful_bytes", "waste_bytes",
               "stores_touched", "cuts", "curve", "complete_domain")
HEAVY_COMMS = {"ctest", "cmake", "make", "gmake", "ninja", "c++", "g++", "clang", "clang++",
               "cc1", "cc1plus", "as", "ld", "ld.lld", "lto-wrapper", "lto1", "merge_bench",
               "publish_bench", "index_bench"}


def utc():
    return datetime.now(timezone.utc).isoformat()


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def plain_gzip_sha(path):
    value = hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def owned_path(name):
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"path outside workspace: {name}")
    return path


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def frequency(cpu=2):
    try:
        return int(Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq").read_text())
    except (OSError, ValueError):
        return None


def ac_power():
    supplies = {}
    for path in sorted(Path("/sys/class/power_supply").glob("*")):
        kind = read_text(path / "type")
        if kind in ("Mains", "USB", "USB_C", "USB_PD"):
            supplies[path.name] = read_text(path / "online")
    values = list(supplies.values())
    return {"online": any(x == "1" for x in values) if values else None, "supplies": supplies}


def cpu_stat(cpu=3):
    label = f"cpu{cpu} "
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith(label):
                values = [int(x) for x in line.split()[1:]]
                # guest/guest_nice are already included in user/nice.
                return {"cpu": cpu, "ticks": values, "total": sum(values[:8]),
                        "idle": values[3] + (values[4] if len(values) > 4 else 0)}
    except (OSError, ValueError, IndexError):
        pass
    return None


def idle_between(before, after):
    if not before or not after:
        return None
    total = after["total"] - before["total"]
    idle = after["idle"] - before["idle"]
    return idle / total if total > 0 and 0 <= idle <= total else None


def process_snapshot():
    """Read comm/stat/affinity only: never cmdline, environ, open files or cwd."""
    result = []
    for directory in Path("/proc").iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            raw = (directory / "stat").read_text()
            tail = raw[raw.rfind(")") + 2:].split()
            pid = int(directory.name)
            try:
                affinity = sorted(os.sched_getaffinity(pid))
            except (OSError, PermissionError):
                affinity = None
            result.append({"pid": pid, "ppid": int(tail[1]), "comm": (directory / "comm").read_text().strip(),
                           "state": tail[0], "cpu": int(tail[36]), "user_ticks": int(tail[11]),
                           "system_ticks": int(tail[12]), "affinity": affinity})
        except (OSError, ValueError, IndexError):
            continue
    return sorted(result, key=lambda item: item["pid"])


def descendants(pid, processes):
    selected = {pid}
    changed = True
    while changed:
        changed = False
        for item in processes:
            if item["ppid"] in selected and item["pid"] not in selected:
                selected.add(item["pid"])
                changed = True
    return selected


def threats(processes, allowed):
    return [item for item in processes if item["pid"] not in allowed and item["state"] != "Z" and
            (item["comm"] in HEAVY_COMMS or item["comm"].startswith(("fuzz_", "tiplog_")))]


def exact(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("cost coefficient must be explicitly exact")
    return Fraction(value)


def cost_signature(row):
    """Include curve and deterministic reconstruction, excluding time/work."""
    return {key: row.get(key) for key in COST_FIELDS}


def parse_cases(path):
    """Preserve each original CASE..END byte chunk exactly, no regeneration."""
    cases = {}
    chunk = []
    identifier = None
    budget = None
    costs = None
    with Path(path).open("rb") as stream:
        for line in stream:
            fields = line.rstrip(b"\r\n").split(b"\t")
            if fields[0] == b"CASE":
                if identifier is not None or len(fields) != 3:
                    raise ValueError(f"malformed CASE in {path}")
                identifier = fields[1].decode()
                budget = int(fields[2])
                costs = None
                chunk = [line]
            elif identifier is not None:
                chunk.append(line)
                if fields[0] == b"COST":
                    if len(fields) != 4 or costs is not None:
                        raise ValueError(f"malformed COST in {path}")
                    costs = tuple(str(exact(x.decode())) for x in fields[1:])
                elif fields[0] == b"END":
                    if len(fields) != 1 or costs is None or identifier in cases:
                        raise ValueError(f"malformed/duplicate END in {path}")
                    cases[identifier] = {"chunk": b"".join(chunk), "budget": budget, "coefficients": costs,
                                         "source": relative(path)}
                    identifier = None
                    chunk = []
            elif line.strip() and not line.startswith(b"#"):
                raise ValueError(f"record outside CASE in {path}")
    if identifier is not None:
        raise ValueError(f"unterminated CASE in {path}")
    return cases


def metadata_matches(row, meta):
    return (row.get("type") == "layout" and row.get("method") == "dp" and
            row.get("budget") == meta["budget"] and row.get("nodes") == meta["nodes"] and
            row.get("classes") == meta["classes"] and row.get("positive_nodes") == meta["positive_nodes"] and
            row.get("total_bytes") == meta["total_bytes"] and
            tuple(exact(row[key]) for key in ("alpha", "beta", "gamma")) ==
            tuple(exact(meta[key]) for key in ("alpha", "beta", "gamma")))


def validate_output(path, order, metadata, reference):
    rows = []
    errors = []
    bad_controls = []
    compared = 0
    statuses = Counter()
    metric_digest = hashlib.sha256()
    with Path(path).open() as stream:
        for index, line in enumerate(stream):
            try:
                row = json.loads(line)
                identifier = row.get("id")
                if index >= len(order) or identifier != order[index]:
                    raise ValueError("case ID/order differs from saved global shuffle")
                meta = metadata[identifier]
                if not metadata_matches(row, meta):
                    raise ValueError("case metadata/budget/coefficient mismatch")
                if row.get("status") == "error" or row.get("solver_status") == "error":
                    raise ValueError("frontend/solver error row")
                for field in ("seconds", "verified_seconds"):
                    value = row.get(field)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                        raise ValueError(f"invalid {field}")
                statuses[(str(row.get("status")), str(row.get("solver_status")))] += 1
                original = reference[identifier]
                if row.get("solver_status") == original.get("solver_status") == "solved":
                    if cost_signature(row) != cost_signature(original):
                        raise ValueError("solved cost/curve/reconstruction differs from original DP")
                    compared += 1
                controls = (row.get("cpu_before") == 2 and not isinstance(row.get("cpu_before"), bool) and
                            row.get("cpu_after") == 2 and not isinstance(row.get("cpu_after"), bool) and
                            row.get("ac_before") is True and row.get("ac_after") is True and
                            all(isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool) and
                                math.isfinite(row[field]) and row[field] > 0
                                for field in ("freq_before_khz", "freq_after_khz")))
                if not controls:
                    bad_controls.append({"id": identifier, **{key: row.get(key) for key in
                                        ("cpu_before", "cpu_after", "freq_before_khz", "freq_after_khz", "ac_before", "ac_after")}})
                metric_digest.update(encoded({"id": identifier, "solver_status": row.get("solver_status"),
                                              **cost_signature(row)}))
                rows.append(row)
            except (ValueError, KeyError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
                errors.append({"line": index + 1, "error": str(error)})
    ids = [row.get("id") for row in rows]
    if len(rows) != 900 or len(set(ids)) != 900 or set(ids) != set(metadata):
        errors.append({"error": "round does not contain exactly the 900 unique DP cases", "valid_rows": len(rows)})
    return {"rows": len(rows), "unique_cases": len(set(ids)), "errors": errors,
            "bad_child_controls": bad_controls, "both_solved_cost_comparisons": compared,
            "status_counts": [{"status": a, "solver_status": b, "count": count} for (a, b), count in sorted(statuses.items())],
            "cost_read_useful_curve_sha256": metric_digest.hexdigest()}


class ControlledFailure(RuntimeError):
    pass


class Runner:
    def __init__(self, args):
        self.args = args
        self.output = owned_path(args.output_dir)
        self.summary_path = owned_path(args.summary)
        self.protocol_path = owned_path(args.protocol)
        self.manifest_path = owned_path(args.manifest)
        self.campaign_path = owned_path(args.campaign)
        self.binary = ROOT / "build/release/tiplog_layout_runtime"
        self.journal = self.output / "journal.jsonl"
        self.session_path = self.output / "session.json"
        self.active = None
        self.summary = {"schema": "tiplog-p7-runtime-campaign-v1", "status": "preparing", "started_utc": utc(),
                        "configuration_count": 900, "warmup_rounds": 1, "measured_rounds": 10,
                        "rounds": [], "attempts": [], "scope": "Controlled repeated DP solver timing; modeled objective costs, nonexclusive host; no physical I/O claim."}

    def event(self, name, **details):
        append(self.journal, {"at_utc": utc(), "event": name, **details})

    def save_summary(self):
        atomic(self.summary_path, self.summary)

    def select_observer(self):
        before = sorted(os.sched_getaffinity(0))
        choices = [6] if 6 in before else [cpu for cpu in before if cpu not in (2, 3)]
        error = None
        selected = choices[0] if choices else None
        if selected is not None:
            try:
                os.sched_setaffinity(0, {selected})
            except OSError as exc:
                error = str(exc)
        self.observer = {"requested_cpu": 6, "initial_affinity": before,
                         "actual_affinity": sorted(os.sched_getaffinity(0)), "error": error,
                         "off_cpu2_and_sibling3": not ({2, 3} & set(os.sched_getaffinity(0)))}

    def prepare(self):
        protocol = load(self.protocol_path)
        for key, expected in EXPECTED.items():
            if protocol.get(key) != expected:
                raise ValueError(f"runtime protocol {key} must be explicitly {expected}")
        original_protocol = load(ROOT / "results/p7/protocol.json")
        self.limits = protocol["solver_limits"]
        if set(self.limits) != set(LIMIT_KEYS) or self.limits != original_protocol["solver_limits"]:
            raise ValueError("runtime caps differ from the original declared P7 caps")
        original = load(self.campaign_path)
        if original.get("status") != "passed":
            raise ValueError("original cost campaign has not passed; runtime execution forbidden")
        manifest = load(self.manifest_path)
        files = [item for item in manifest["files"] if item.get("kind") == "synthetic"]
        if len(manifest["files"]) != 32 or len(files) != 8 or sum(item["cases"] for item in files) != 900:
            raise ValueError("input manifest must retain all 32 files and all eight synthetic batches / 900 cases")
        identities = {}
        paths = [self.binary, self.protocol_path, self.manifest_path, self.campaign_path,
                 ROOT / "results/p7/protocol.json", Path(__file__), ROOT / "scripts/env_capture.py",
                 ROOT / "results/p7/runtime-method.md",
                 ROOT / "data/manifest.json", ROOT / "results/p1/data-gate.json",
                 ROOT / "build/release/CMakeCache.txt", ROOT / "build/release/compile_commands.json"]
        paths += sorted((ROOT / "src/tiplog/layout").glob("*.*"))
        paths += sorted((ROOT / "tools/tiplog_layout").glob("*.*"))
        paths += [ROOT / "cmake/p7_layout.cmake"]
        paths += sorted((ROOT / "build/release/CMakeFiles").glob("tiplog_layout*/*.make"))
        for path in paths:
            identities[relative(path)] = sha(path)
        self.tool_identities = {}
        cache = (ROOT / "build/release/CMakeCache.txt").read_text()
        compiler = next((line.split("=", 1)[1] for line in cache.splitlines()
                         if line.startswith("CMAKE_CXX_COMPILER:") and "=" in line), None)
        for label, command in [("compiler", compiler), ("time", "/usr/bin/time"),
                               ("taskset", shutil.which("taskset")), ("setarch", shutil.which("setarch"))]:
            if not command:
                raise ValueError(f"required release/tool executable unavailable: {label}")
            # CMake presets may retain a PATH-resolved compiler name such as
            # g++, rather than an absolute FILEPATH cache entry.
            path = Path(shutil.which(command) or command).resolve()
            self.tool_identities[label] = {"path": str(path), "sha256": sha(path)}
        # Check that the timing frontend still calls the exact accepted solver.
        for name, expected in original.get("identities", {}).items():
            if name.startswith("src/tiplog/layout/") and sha(owned_path(name)) != expected:
                raise ValueError(f"accepted solver library changed: {name}")
        meta_path = owned_path(manifest["metadata_path"])
        if sha(meta_path) != manifest["metadata_sha256"]:
            raise ValueError("metadata identity differs from generation manifest")
        identities[relative(meta_path)] = manifest["metadata_sha256"]
        meta = load(meta_path)
        self.metadata = {}
        for identifier, item in meta["case_index"].items():
            if item.get("kind") == "synthetic":
                classes = meta["partition_workloads"][item["classes_metadata_key"]]
                self.metadata[identifier] = {**item, "classes": classes["effective_class_count"]}
        del meta
        gc.collect()
        self.cases = {}
        for item in files:
            path = owned_path(item["path"])
            if sha(path) != item["sha256"]:
                raise ValueError(f"original synthetic input changed: {path}")
            identities[relative(path)] = item["sha256"]
            chunks = parse_cases(path)
            if len(chunks) != item["cases"] or set(chunks) & set(self.cases):
                raise ValueError("original synthetic CASE count/uniqueness mismatch")
            self.cases.update(chunks)
        if len(self.metadata) != 900 or set(self.cases) != set(self.metadata):
            raise ValueError("synthetic chunks do not match the complete metadata population")
        self.reference = {}
        by_input = {item["input"]: item for item in original["files"] if item.get("kind") == "synthetic"}
        for item in files:
            accepted = by_input.get(item["path"])
            if not accepted or accepted.get("status") != "passed" or accepted.get("input_sha256") != item["sha256"]:
                raise ValueError("original cost campaign lacks accepted matching synthetic batch")
            path = owned_path(accepted["output"])
            if sha(path) != accepted["output_sha256"]:
                raise ValueError("original synthetic DP output changed")
            identities[relative(path)] = accepted["output_sha256"]
            with path.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get("method") != "dp":
                        continue
                    identifier = row.get("id")
                    if identifier in self.reference or identifier not in self.metadata or not metadata_matches(row, self.metadata[identifier]):
                        raise ValueError("original DP output IDs/metadata differ")
                    self.reference[identifier] = row
        if set(self.reference) != set(self.cases):
            raise ValueError("original accepted DP rows do not cover all 900 cases")
        for identifier, case in self.cases.items():
            metadata = self.metadata[identifier]
            if case["budget"] != metadata["budget"] or tuple(exact(x) for x in case["coefficients"]) != tuple(
                    exact(metadata[x]) for x in ("alpha", "beta", "gamma")):
                raise ValueError("original case chunks differ from metadata")
        self.identities = identities
        self.identity_fingerprint = fingerprint({"project": identities, "toolchain": self.tool_identities})
        randomizer = random.Random(20191230)
        self.orders = []
        for _ in range(11):
            order = sorted(self.cases)
            randomizer.shuffle(order)
            self.orders.append(order)
        self.summary.update(protocol=relative(self.protocol_path), identities=identities,
                            identity_fingerprint=self.identity_fingerprint, solver_limits=self.limits,
                            toolchain_identities=self.tool_identities,
                            observer=self.observer, original_campaign=relative(self.campaign_path),
                            journal=relative(self.journal), session=relative(self.session_path))
        data = load(ROOT / "data/manifest.json")
        p1 = load(ROOT / "results/p1/data-gate.json")
        self.summary["local_data_provenance"] = {
            "gzip": {key: data.get(key) for key in ("path", "sha256", "size_bytes", "source_url")},
            "source_incomplete": data.get("stream_characterization", {}).get("binaryfile_incomplete"),
            "traces": {hierarchy: {key: item.get(key) for key in ("path", "sha256", "bytes", "repeat_path", "repeat_sha256")}
                       for hierarchy, item in p1.get("traces", {}).items()},
            "scope": "Accepted local-data provenance retained; synthetic runtime rounds consume only the saved synthetic CASE chunks, without rereading the source gzip or real traces."}

    def terminate_active(self):
        if self.active is None or self.active.poll() is not None:
            return
        try:
            os.killpg(self.active.pid, signal.SIGTERM)
            self.active.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.active.pid, signal.SIGKILL)
            except OSError:
                pass
            self.active.wait()

    def environment(self):
        prefix = self.output / f"environment-{stamp()}"
        destination = Path(str(prefix) + ".json")
        log = Path(str(prefix) + ".log")
        argv = [sys.executable, str(ROOT / "scripts/env_capture.py"), "--cpu", "2", "--preset", "release"]
        started = utc()
        before = time.monotonic()
        with destination.open("w") as stdout, log.open("w") as stderr:
            self.active = subprocess.Popen(argv, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
            next_progress = time.monotonic() + 20
            while self.active.poll() is None:
                if time.monotonic() >= next_progress:
                    print("runtime: capturing environment before measurements", flush=True)
                    next_progress = time.monotonic() + 20
                time.sleep(1)
            exit_code = self.active.returncode
        self.active = None
        record = {"argv": argv, "cwd": str(ROOT), "started_utc": started, "finished_utc": utc(),
                  "duration_seconds": time.monotonic() - before, "exit_code": exit_code,
                  "status": "passed" if exit_code == 0 else "failed", "output": relative(destination),
                  "output_sha256": sha(destination), "log": relative(log), "log_sha256": sha(log)}
        record_path = Path(str(prefix) + ".command.json")
        atomic(record_path, record)
        if exit_code:
            raise ValueError("whole-environment capture failed")
        environment = load(destination)
        probe = environment["controls"]["per_process_aslr_probe"]
        self.aslr = {"probe": probe, "system_randomize_va_space": environment["controls"].get("aslr_randomize_va_space"),
                     "mode": "per_process_disabled" if probe.get("returncode") == 0 else "ASLR_on_fallback",
                     "privileged_settings_changed": False}
        self.aslr_prefix = ["setarch", platform.machine(), "-R"] if probe.get("returncode") == 0 else []
        self.environment_ref = {"path": relative(destination), "sha256": sha(destination),
                                "command_record": relative(record_path), "command_record_sha256": sha(record_path)}
        self.summary.setdefault("environment_captures", []).append(self.environment_ref)
        self.summary.update(aslr=self.aslr)
        self.event("environment_captured", **self.environment_ref, aslr=self.aslr["mode"])

    def sample_processes(self, audit_path, phase, allowed=None):
        processes = process_snapshot()
        allowed = allowed or {os.getpid()}
        found = threats(processes, allowed)
        append(audit_path, {"at_utc": utc(), "phase": phase, "processes": processes,
                            "project_build_test_fuzz_threats": found,
                            "limits": "comm/stat/affinity snapshots only; short-lived activity between samples can be missed; host not exclusive"})
        return processes, found

    def settle(self, record, status_path, audit_path):
        before = time.monotonic()
        record["settle"] = {"required_seconds": 60, "started_utc": utc(), "started_monotonic": before,
                            "complete": False, "cpu3_before": cpu_stat(3)}
        atomic(status_path, record)
        self.event("settle_started", round=record["round"], attempt=record["attempt"], required_seconds=60)
        next_progress = before
        try:
            while True:
                _, found = self.sample_processes(audit_path, "settle")
                if found:
                    record["overlap_threats"] = found
                    raise ControlledFailure("build/test/fuzz/engine/optimizer process observed during required settling")
                now = time.monotonic()
                if now >= next_progress:
                    print(f"runtime round {record['round']}/10: settling {min(now-before,60):.0f}/60 s", flush=True)
                    next_progress = now + 20
                remaining = 60 - (now - before)
                if remaining <= 0:
                    break
                time.sleep(min(10, remaining))
            record["settle"]["complete"] = True
        finally:
            after = time.monotonic()
            record["settle"].update(finished_utc=utc(), finished_monotonic=after,
                                     actual_seconds=after-before, cpu3_after=cpu_stat(3))
            record["settle"]["cpu3_idle_ratio"] = idle_between(record["settle"]["cpu3_before"], record["settle"]["cpu3_after"])
            atomic(status_path, record)

    def prepare_input(self, round_number, prefix):
        order = self.orders[round_number]
        plain = Path(str(prefix) + ".input.tsv")
        compressed = Path(str(prefix) + ".input.tsv.gz")
        order_path = Path(str(prefix) + ".order.json")
        plain_hash = hashlib.sha256()
        with plain.open("wb") as output:
            for identifier in order:
                chunk = self.cases[identifier]["chunk"]
                output.write(chunk)
                plain_hash.update(chunk)
        with plain.open("rb") as source, compressed.open("wb") as output:
            with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=6) as zipped:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    zipped.write(chunk)
        atomic(order_path, {"round": round_number, "kind": "warmup" if round_number == 0 else "measured",
                            "seed": 20191230, "shuffle": "Python random.Random seeded once; shuffle sorted global 900-case IDs once per round",
                            "ids": order, "plain_input_sha256": plain_hash.hexdigest(),
                            "source_manifest": relative(self.manifest_path), "source_manifest_sha256": self.identities[relative(self.manifest_path)]})
        return {"plain": plain, "gzip": compressed, "order": order_path, "plain_sha256": plain_hash.hexdigest()}

    def attempt_round(self, round_number):
        prefix = self.output / f"round-{round_number:02}-{stamp()}"
        status_path = Path(str(prefix) + ".status.json")
        audit_path = Path(str(prefix) + ".process-audit.jsonl")
        output = Path(str(prefix) + ".jsonl")
        log = Path(str(prefix) + ".log")
        resources = Path(str(prefix) + ".resources.txt")
        record = {"round": round_number, "kind": "warmup" if round_number == 0 else "measured", "attempt": prefix.name,
                  "status": "preparing", "started_utc": utc(), "identity_fingerprint": self.identity_fingerprint,
                  "environment": self.environment_ref, "aslr": self.aslr, "observer": self.observer,
                  "status_record": relative(status_path), "process_audit": relative(audit_path),
                  "output": relative(output), "log": relative(log), "resources": relative(resources)}
        atomic(status_path, record)
        self.event("round_preparing", round=round_number, record=relative(status_path))
        inputs = None
        try:
            inputs = self.prepare_input(round_number, prefix)
            record.update(input=relative(inputs["plain"]), input_plain_sha256=inputs["plain_sha256"],
                          input_gzip=relative(inputs["gzip"]), input_gzip_sha256=sha(inputs["gzip"]),
                          order=relative(inputs["order"]), order_sha256=sha(inputs["order"]))
            # Compressing/serializing/hashing finishes before the mandatory idle block.
            record["preparation_finished_utc"] = utc()
            self.settle(record, status_path, audit_path)
            record["controls_before"] = {"at_utc": utc(), "frequency_khz": frequency(2), "ac": ac_power()}
            record["cpu3_before"] = cpu_stat(3)
            _, found = self.sample_processes(audit_path, "immediately_before_round")
            if found:
                record["overlap_threats"] = found
                raise ControlledFailure("overlapping heavy process before runtime child")
            argv = ["/usr/bin/time", "-v", "-o", str(resources), "taskset", "-c", "2", *self.aslr_prefix,
                    str(self.binary), "--input", str(inputs["plain"]), "--output", str(output), "--methods", "dp"]
            for key in LIMIT_KEYS:
                argv.extend(["--" + key.replace("_", "-"), str(self.limits[key])])
            record.update(argv=argv, cwd=str(ROOT), status="running", measurement_started_utc=utc())
            started = time.monotonic()
            record["measurement_started_monotonic"] = started
            with log.open("w") as stream:
                self.active = subprocess.Popen(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                               env={**os.environ, "LC_ALL": "C"}, start_new_session=True)
                record["controlled_environment"] = {"LC_ALL": "C"}
                record["launcher_pid"] = self.active.pid
                atomic(status_path, record)
                self.event("round_started", round=round_number, launcher_pid=self.active.pid, argv=argv)
                next_progress = started
                overlap = []
                while True:
                    processes = process_snapshot()
                    allowed = descendants(self.active.pid, processes) | {os.getpid()}
                    children = [p for p in processes if p["pid"] in allowed and p["pid"] != self.active.pid and p["comm"].startswith("tiplog_layout")]
                    if children:
                        record["process_pid"] = children[0]["pid"]
                    elif "process_pid" not in record:
                        # GNU time's direct child execs taskset/setarch/frontend
                        # without changing PID. Capture it even before exec.
                        direct = [p for p in processes if p["ppid"] == self.active.pid]
                        if len(direct) == 1:
                            record["process_pid"] = direct[0]["pid"]
                    found = threats(processes, allowed)
                    if found:
                        overlap.extend(found)
                    now = time.monotonic()
                    if now >= next_progress:
                        append(audit_path, {"at_utc": utc(), "phase": "runtime_round", "processes": processes,
                                            "project_build_test_fuzz_threats": found})
                        print(f"runtime round {round_number}/10: child running {now-started:.0f} s", flush=True)
                        next_progress = now + 20
                    if self.active.poll() is not None:
                        break
                    try:
                        self.active.wait(timeout=5 if "process_pid" in record else .05)
                    except subprocess.TimeoutExpired:
                        pass
                record["exit_code"] = self.active.returncode
                self.active = None
            finished = time.monotonic()
            record.update(measurement_finished_utc=utc(), measurement_finished_monotonic=finished,
                          observer_process_wall_seconds=finished-started, overlap_threats=overlap)
            record["controls_after"] = {"at_utc": utc(), "frequency_khz": frequency(2), "ac": ac_power()}
            record["cpu3_after"] = cpu_stat(3)
            record["cpu3_idle_ratio"] = idle_between(record["cpu3_before"], record["cpu3_after"])
            _, after_threats = self.sample_processes(audit_path, "immediately_after_round")
            overlap.extend(after_threats)
            record["overlap_threats"] = overlap
            validation = validate_output(output, self.orders[round_number], self.metadata, self.reference) if output.is_file() else {
                "rows": 0, "errors": [{"error": "output absent"}], "bad_child_controls": []}
            record["validation"] = validation
            bracket_controls = all(record[f"controls_{side}"]["ac"]["online"] is True and
                                   isinstance(record[f"controls_{side}"]["frequency_khz"], int) and
                                   record[f"controls_{side}"]["frequency_khz"] > 0 for side in ("before", "after"))
            record["controls_validated"] = bool(bracket_controls and not validation["bad_child_controls"] and not overlap and
                                                record.get("process_pid") is not None and
                                                record["settle"]["complete"] and record["settle"]["actual_seconds"] >= 60)
            if record["exit_code"] != 0 or validation["errors"]:
                record["status"] = "failed"
            elif not record["controls_validated"]:
                record["status"] = "control_failed"
            else:
                record["status"] = "passed"
        except KeyboardInterrupt:
            self.terminate_active()
            record.update(status="interrupted", error="interrupt; any next attempt must repeat the full settling block")
            raise
        except ControlledFailure as error:
            record.update(status="control_failed", controls_validated=False, error=str(error))
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
            self.terminate_active()
            record.update(status="failed", error=f"{type(error).__name__}: {error}")
        finally:
            record["finished_utc"] = utc()
            artifacts = {}
            for path in (output, log, resources, audit_path):
                if path.is_file():
                    artifacts[relative(path)] = sha(path)
            if inputs is not None:
                for key in ("gzip", "order"):
                    artifacts[relative(inputs[key])] = sha(inputs[key])
                # The complete lossless gzip, input hash and order are preserved.
                # Delete only this attempt's plaintext scratch copy, never inputs.
                if inputs["plain"].is_file():
                    inputs["plain"].unlink()
                record["plaintext_removed_after_round"] = True
            else:
                for suffix in (".input.tsv", ".input.tsv.gz", ".order.json"):
                    partial = Path(str(prefix) + suffix)
                    if partial.is_file():
                        artifacts[relative(partial)] = sha(partial)
            record["artifact_identities"] = artifacts
            if output.is_file():
                record["output_sha256"] = artifacts[relative(output)]
            atomic(status_path, record)
            self.event("round_finished", round=round_number, status=record["status"], record=relative(status_path), record_sha256=sha(status_path))
            self.summary["attempts"].append({"round": round_number, "status": record["status"], "record": relative(status_path), "record_sha256": sha(status_path)})
            self.save_summary()
        if record["status"] == "passed":
            atomic(self.output / f"round-{round_number:02}.accepted.json", record)
        return record

    def resume(self):
        if self.session_path.exists():
            session = load(self.session_path)
            if session.get("identity_fingerprint") != self.identity_fingerprint or session.get("identities") != self.identities:
                raise ValueError("resume rejected: protocol/source/binary/build/input/original-evidence identities changed")
            if self.summary_path.exists():
                previous = load(self.summary_path)
                if previous.get("identity_fingerprint") != self.identity_fingerprint:
                    raise ValueError("resume summary identity differs")
                for field in ("attempts", "environment_captures", "started_utc"):
                    if field in previous:
                        self.summary[field] = previous[field]
        else:
            atomic(self.session_path, {"schema": "tiplog-p7-runtime-session-v1", "created_utc": utc(),
                                       "identity_fingerprint": self.identity_fingerprint, "identities": self.identities,
                                       "toolchain_identities": self.tool_identities,
                                       "configuration_count": 900, "rounds": 11, "seed": 20191230})
        self.accepted = {}
        for number in range(11):
            path = self.output / f"round-{number:02}.accepted.json"
            if not path.exists():
                continue
            record = load(path)
            if record.get("status") != "passed" or not record.get("controls_validated") or record.get("identity_fingerprint") != self.identity_fingerprint:
                raise ValueError(f"resume rejected: round {number} acceptance/identity")
            if record.get("round") != number or record.get("kind") != ("warmup" if number == 0 else "measured"):
                raise ValueError("resume rejected: round number/kind")
            if load(owned_path(record["status_record"])) != record:
                raise ValueError("resume rejected: accepted/status record disagreement")
            for name, expected in record["artifact_identities"].items():
                if sha(owned_path(name)) != expected:
                    raise ValueError(f"resume rejected: saved round artifact changed: {name}")
            if plain_gzip_sha(owned_path(record["input_gzip"])) != record["input_plain_sha256"]:
                raise ValueError("resume rejected: compressed input does not reproduce the accepted plain hash")
            if load(owned_path(record["order"]))["ids"] != self.orders[number]:
                raise ValueError("resume rejected: shuffle order changed")
            validation = validate_output(owned_path(record["output"]), self.orders[number], self.metadata, self.reference)
            if validation["errors"] or validation["bad_child_controls"] or validation != record["validation"]:
                raise ValueError("resume rejected: output/control validation differs")
            self.accepted[number] = record
        self.summary["rounds"] = [self.compact(self.accepted[key]) for key in sorted(self.accepted)]

    @staticmethod
    def compact(record):
        keys = ("round", "kind", "status", "output", "output_sha256", "process_pid", "launcher_pid",
                "controls_before", "controls_after", "controls_validated", "cpu3_idle_ratio", "settle",
                "validation", "environment", "status_record", "input_gzip", "input_gzip_sha256", "input_plain_sha256",
                "order", "order_sha256", "observer_process_wall_seconds")
        result = {key: record.get(key) for key in keys}
        result["record_sha256"] = sha(owned_path(record["status_record"]))
        return result

    def frequency_flags(self):
        rows = []
        values = []
        for number in range(1, 11):
            with owned_path(self.accepted[number]["output"]).open() as stream:
                for line in stream:
                    row = json.loads(line)
                    samples = [row["freq_before_khz"], row["freq_after_khz"]]
                    values.extend(samples)
                    rows.append({"round": number, "id": row["id"], "freq_before_khz": samples[0], "freq_after_khz": samples[1]})
        median = statistics.median(values)
        median_exact = Fraction(median)
        counts = Counter()
        for row in rows:
            row["more_than_10_percent_from_session_median"] = any(
                abs(Fraction(row[key]) - median_exact) * 10 > median_exact
                for key in ("freq_before_khz", "freq_after_khz"))
            counts[row["round"]] += int(row["more_than_10_percent_from_session_median"])
        path = self.output / "frequency-flags.json"
        flags = {"status": "reported", "computed_utc": utc(), "measured_session_median_khz": median,
                 "sample_count": len(values), "flagged_case_rows": sum(counts.values()), "per_round_flagged_case_rows": dict(counts),
                 "policy": "Post-session descriptive >10% flag; every otherwise valid row/round retained, no noise filtering or replacement.", "rows": rows}
        atomic(path, flags)
        self.summary["frequency_noise"] = {key: value for key, value in flags.items() if key != "rows"}
        self.summary["frequency_noise"].update(path=relative(path), sha256=sha(path))

    def run(self):
        self.output.mkdir(parents=True, exist_ok=True)
        with (self.output / ".runner.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.select_observer()
            self.prepare()
            self.resume()
            if len(self.accepted) < 11:
                self.environment()
            self.summary["status"] = "running"
            self.save_summary()
            for number in range(11):
                if number in self.accepted:
                    print(f"runtime round {number}/10: verified saved accepted round", flush=True)
                    continue
                record = self.attempt_round(number)
                if record["status"] != "passed":
                    self.summary.update(status=record["status"], stopped_utc=utc(), remaining_rounds=[n for n in range(11) if n not in self.accepted])
                    self.save_summary()
                    return 1
                self.accepted[number] = record
                self.summary["rounds"] = [self.compact(self.accepted[key]) for key in sorted(self.accepted)]
                self.save_summary()
                print(f"runtime round {number}/10: passed all 900 DP rows and controls", flush=True)
            for name, expected in self.identities.items():
                if sha(owned_path(name)) != expected:
                    raise ValueError(f"identity changed during runtime campaign: {name}")
            for item in self.tool_identities.values():
                if sha(Path(item["path"])) != item["sha256"]:
                    raise ValueError(f"toolchain identity changed during runtime campaign: {item['path']}")
            self.frequency_flags()
            self.summary.update(status="passed", completed_utc=utc(), accepted_rounds=11,
                                accepted_measured_rounds=10, warmup_rows=900, measured_rows=9000,
                                limitations=["Host not exclusive; CPU3 /proc/stat idle ratios are descriptive.",
                                             "Frequency bracket samples do not prove stable frequency; every >10% flag retained.",
                                             "Timeout/state/representation limits remain non-solved observations under unchanged caps.",
                                             "Solver seconds exclude preparation and independent CLI evaluation; process wall time is separately recorded."])
            self.event("campaign_passed", accepted_rounds=11, measured_rounds=10)
            self.save_summary()
            print(f"runtime campaign passed: 1 warm-up + 10 measured fresh processes, {self.args.summary}", flush=True)
            return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default="results/p7/runtime-supplement.json")
    parser.add_argument("--manifest", default="results/p7/input-manifest.json")
    parser.add_argument("--campaign", default="results/raw/P7/studies/campaign.json")
    parser.add_argument("--output-dir", default="results/raw/P7/runtime")
    parser.add_argument("--summary", default="results/p7/runtime-campaign.json")
    args = parser.parse_args(argv)
    runner = Runner(args)
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        return runner.run()
    except KeyboardInterrupt:
        runner.terminate_active()
        runner.summary.update(status="interrupted", stopped_utc=utc(), error="Interrupted; completed accepted rounds retained, interrupted settling must restart fully.")
        if runner.output.exists():
            runner.event("campaign_interrupted")
            runner.save_summary()
        print("runtime interrupted; preserved completed rounds and partial attempt", flush=True)
        return 130
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
        runner.terminate_active()
        # Keep an existing session/result intact when rejecting a different
        # source/protocol invocation; preserve the rejection separately.
        if runner.output.exists():
            rejection = runner.output / f"invocation-failure-{stamp()}.json"
            atomic(rejection, {"status": "failed", "at_utc": utc(), "error": f"{type(error).__name__}: {error}",
                               "argv": [sys.executable, str(Path(__file__)), *sys.argv[1:]]})
            runner.event("invocation_failed", error=str(error), record=relative(rejection))
        print(f"runtime runner failed: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
