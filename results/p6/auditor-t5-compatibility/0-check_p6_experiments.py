#!/usr/bin/env python3
"""Audit saved P6 process experiments against prepared independent expectations.

Never executes an engine, benchmark, compiler, converter, or oracle accelerator.
Each prepared workload is loaded once. Large input hashes are cached, and JSONL
offset indexes keep the full session's normalized observations out of memory.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py"))
from tiplog_py.exp.oracle import validate

STREAM = ("out_digest", "oracle_digest", "seq_sha256", "payload_sha256", "sink64", "checkpoint", "error")
STATUSES = {"ok", "history_expired", "fell_behind", "invalid_config", "crash", "oracle_mismatch"}


def read_json(path):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt") as stream:
            return json.load(stream)
    return json.loads(path.read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def stable_id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


class Audit:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.checks = 0
        self.failures = []
        self.hashes = {}

    def check(self, condition, label, detail=None):
        self.checks += 1
        if not condition:
            self.failures.append({"check": label, "detail": detail})

    def path(self, value):
        path = Path(value)
        if path.is_absolute():
            return path
        rooted = ROOT / path
        return rooted if rooted.exists() else self.directory / path

    def sha(self, value):
        path = self.path(value).resolve()
        if path not in self.hashes:
            with path.open("rb") as stream:
                self.hashes[path] = hashlib.file_digest(stream, "sha256").hexdigest()
        return self.hashes[path]

    def identity(self, item, label):
        path = self.path(item["path"])
        self.check(path.is_file(), label + ":exists", str(path))
        if path.is_file() and item.get("sha256") is not None:
            self.check(self.sha(path) == item["sha256"], label + ":SHA256", str(path))

    def artifacts(self, value, label):
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                self.identity(value, label)
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    self.artifacts(child, label + "/" + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.artifacts(child, label + f"/{index}")


class RowIndex:
    """Byte-offset index, not an in-memory copy of all normalized payloads."""
    def __init__(self, path, audit):
        self.path = Path(path)
        self.offsets = defaultdict(list)
        if not self.path.exists():
            return
        with self.path.open("rb") as stream:
            while True:
                position = stream.tell()
                line = stream.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                row = json.loads(line)
                process = row.get("process_round_id", row.get("process_id"))
                audit.check(process is not None, self.path.name + ":process identity")
                self.offsets[process].append((position, len(line)))

    def rows(self, process):
        result = []
        if self.offsets.get(process):
            with self.path.open("rb") as stream:
                for offset, size in self.offsets[process]:
                    stream.seek(offset)
                    result.append(json.loads(stream.read(size)))
        return result


def output_rows(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def flag(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def command_ok(record):
    return record.get("returncode") == 0 and all(
        sample.get("power", {}).get("ac_online") is True
        for sample in [record.get("before", {}), record.get("after", {}), *record.get("observations", [])])


def prefill(audit, actuals, case, *, enabled, label):
    rows = [row for row in actuals if row.get("kind") == "prefill"]
    audit.check(len(rows) == 1, label + ":one prefill")
    if len(rows) != 1:
        return {}
    row = rows[0]
    expected, layout, workload = case["prefill_digest"], case["layout"], case["workload"]
    for field, value in {"status": "ok", "publications": expected["out_count"],
                         "publish_sink64": expected["sink64"], "index_enabled": enabled,
                         "ring_bytes": workload["ring_bytes"], "block_entries": workload["block_entries"],
                         "pressure_data_evicted": 0, "pad_bytes_appended": layout["pad_bytes"],
                         "capacity_and_pressure_data_evicted": expected["out_count"] - layout["retained_data"]}.items():
        audit.check(row.get(field) == value, label + ":" + field)
    for field in ("head_seq", "tail_seq", "head_pos", "tail_pos"):
        audit.check(row.get(field) == layout[field], label + ":independent layout:" + field)
    audit.check(row.get("cpu_start") == row.get("cpu_end") == 2, label + ":CPU2")
    for field in ("publish_cpu_ns", "publish_wall_ns"):
        value = row.get(field)
        audit.check(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0, label + ":duration:" + field)
    for field, value in workload.get("synthetic_summary", {}).items():
        if field not in {"records", "observed_run_mean"}:
            audit.check(row.get(field) == value, label + ":synthetic summary:" + field)
    return row


def memory(audit, actuals, case, label):
    memories = [row for row in actuals if row.get("kind") == "memory"]
    allocators = [row for row in actuals if row.get("kind") == "allocator"]
    audit.check(len(memories) == len(allocators) == 1, label + ":one memory and allocator boundary")
    if len(memories) != 1 or len(allocators) != 1:
        return None, None
    m, alloc = memories[0], allocators[0]
    audit.check(m.get("status") == "ok" and m.get("recount_equal") is True, label + ":exact recount")
    audit.check(alloc.get("status") == "ok" and alloc.get("stats_equal") is True, label + ":allocator stats equality")
    for field in ("head_seq", "tail_seq", "head_pos", "tail_pos"):
        audit.check(m.get(field) == case["layout"][field], label + ":layout:" + field)
    g, amounts = m["gauges"], m["memory"]
    audit.check(g["live_entries"] == m["retained_records"] == case["layout"]["retained_data"], label + ":retained postings")
    audit.check(g["allocated_blocks"] + g["free_blocks"] == m["blocks"], label + ":block conservation")
    audit.check(g["allocated_entries"] == g["live_entries"] + g["expired_allocated_entries"], label + ":allocated entries")
    audit.check(sum(g[key] for key in ("live_entries", "expired_allocated_entries", "open_slack", "sealed_partial_slack", "free_block_slots")) == m["blocks"] * m["block_entries"], label + ":slot conservation")
    components = ("metadata_reserved_bytes", "entries_reserved_bytes", "sealed_flags_reserved_bytes", "heap_reserved_bytes", "partition_state_reserved_bytes", "partition_list_reserved_bytes", "control_bytes")
    audit.check(sum(amounts[key] for key in components) == amounts["reserved_bytes"], label + ":reserved byte recount")
    audit.check(amounts["entries_reserved_bytes"] == m["blocks"] * m["block_entries"] * 4, label + ":delta backing bytes")
    charged = (alloc["after"]["uordblks"] + alloc["after"]["hblkhd"] - alloc["before"]["uordblks"] - alloc["before"]["hblkhd"])
    audit.check(alloc["requested_reserved_bytes"] == amounts["reserved_bytes"] and alloc["charged_delta_bytes"] == charged and alloc["observed_allocator_overhead_bytes"] == charged - amounts["reserved_bytes"], label + ":signed allocator arithmetic")
    audit.check(alloc["schedule_rows"] == case["prefill_digest"]["out_count"], label + ":actual schedule coverage")
    return m, alloc


def transport(audit, record, requested, term_hashes, dictionary_path, label):
    argv = record["argv"]
    path = audit.path(flag(argv, "--requests"))
    audit.check(audit.sha(path) == record.get("requests_sha256"), label + ":request TSV hash")
    identity = record.get("term_dictionary")
    audit.check(isinstance(identity, dict), label + ":dictionary identity recorded")
    if identity:
        audit.identity(identity, label + ":dictionary")
        audit.check(audit.path(identity["path"]).resolve() == dictionary_path.resolve() == audit.path(flag(argv, "--term-dictionary")).resolve(), label + ":dictionary command path")
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    by_id = {row["id"]: row for row in rows}
    audit.check(len(by_id) == len(rows) and set(by_id) == set(requested), label + ":exact TSV request IDs")
    for identity, request in requested.items():
        if identity not in by_id:
            continue
        row = by_id[identity]
        terms = row["terms"]
        digest = terms[1:] if terms.startswith("@") else hashlib.sha256(terms.encode()).hexdigest()
        audit.check(digest == term_hashes[identity], label + ":subscription identity:" + identity)
        expected = {"experiment": request["exp"], "after_seq": str(request["after_seq"]), "mode": request["mode"], "kernel": request["kernel"], "cache": request["cache_treatment"], "batch": str(request.get("batch", 1024)), "readers": str(request.get("readers", 1))}
        audit.check(all(row.get(key) == value for key, value in expected.items()), label + ":TSV semantics:" + identity)


def group_id(request):
    base = {"exp": "T2", "R": request["reader_count"], "cache": request["cache_treatment"], "C": request["ring_bytes"], "B": request["block_entries"]}
    return stable_id(dict(base, mode=request["mode"], kernel=request["kernel"]))


def audit_session(plan_path, directory, repetitions=None):
    directory = Path(directory).resolve()
    audit = Audit(directory)
    plan_path = audit.path(plan_path)
    plan, state = read_json(plan_path), read_json(directory / "state.json")
    count = state["repetitions"] if repetitions is None else repetitions
    minimum = 30 if plan["suite"] == "pilot" else 10
    audit.check(count >= minimum and state["repetitions"] == count, "required exact measured repetitions")
    audit.check(state.get("status") == "passed", "terminal session passed")
    audit.check(state.get("excluded_saved_warmups") == 1, "one explicitly saved warm-up")
    audit.check(audit.sha(plan_path) == state["plan_sha256"], "prepared plan identity")
    audit.check(audit.sha(plan["config"]) == plan["config_sha256"], "configuration identity")
    provenance = read_json(directory / "provenance.json")
    for kind in ("source_files", "binaries", "inputs"):
        audit.check(bool(provenance.get(kind)), "nonempty provenance:" + kind)
        for item in provenance.get(kind, []):
            audit.identity(item, "frozen " + kind)
    source_names = {str(item["path"]) for item in provenance.get("source_files", [])}
    frozen_binaries = {audit.path(item["path"]).resolve(): item["sha256"] for item in provenance.get("binaries", [])}
    for required in ("py/tiplog_py/exp/run.py", "py/tiplog_py/exp/oracle.py", "CMakeLists.txt"):
        audit.check(any(name.endswith(required) for name in source_names), "frozen scope:" + required)
    indexes = {name: RowIndex(directory / name, audit) for name in ("runs.jsonl", "reader-runs.jsonl", "process-metadata.jsonl")}
    completions = state["completed_processes"]
    audit.check(len({row["id"] for row in completions}) == len(completions), "unique completed process rounds")
    workload_ids = [row["id"] for row in plan["workloads"]]
    audit.check(len(set(workload_ids)) == len(workload_ids), "unique prepared workload IDs")
    audit.check({row["workload_id"] for row in completions} == set(workload_ids), "complete workload set")
    reports, raw_counts, normalized_counts, used_outputs = [], Counter(), Counter(), set()
    consumed_readers = set()
    for description in plan["workloads"]:
        case_path = audit.path(description["path"])
        audit.check(audit.sha(case_path) == description["sha256"], "prepared case hash:" + description["id"])
        case = read_json(case_path)  # Release before loading the next workload.
        workload = case["workload"]
        requested = {row["id"]: row for row in workload["requests"]}
        audit.check(len(requested) == len(workload["requests"]) == description["requests"] and set(requested) == set(case["expected"]), "prepared request/expectation coverage:" + workload["id"])
        term_hashes = {identity: hashlib.sha256(row["terms"].encode()).hexdigest() for identity, row in requested.items()}
        block = directory / workload["id"]
        dictionary_path = block / "subscription-terms.tsv"
        dictionary = {}
        with dictionary_path.open() as stream:
            for line in stream:
                alias, terms = line.rstrip("\n").split("\t", 1)
                audit.check(alias not in dictionary and hashlib.sha256(terms.encode()).hexdigest() == alias, "dictionary semantic hash:" + workload["id"])
                dictionary[alias] = True
        audit.check(set(dictionary) == set(term_hashes.values()), "exact subscription dictionary:" + workload["id"])
        rounds = [row for row in completions if row["workload_id"] == workload["id"]]
        audit.check(Counter(row["rep"] for row in rounds) == Counter(range(-1, count)), "one warm-up and every exact measured round:" + workload["id"])
        pids = set()
        registry_identities = {True: set(), False: set()}
        t2_groups = defaultdict(list)
        for request in requested.values():
            if request["exp"] == "T2":
                t2_groups[group_id(request)].append(request)
        normalized_ids = {identity for identity, row in requested.items() if row["exp"] != "T2"} | set(t2_groups)
        for completion in rounds:
            process = completion["id"]
            label = workload["id"] + "/" + process
            start_failures = len(audit.failures)
            try:
                record = read_json(block / (process + ".command.json"))
                audit.artifacts(record, label + ":recorded artifact")
                argv = record["argv"]
                audit.check(record.get("process_id") == process and record.get("rep") == completion["rep"] and record.get("warmup") == (completion["rep"] == -1), label + ":round metadata")
                audit.check(record.get("pid") not in pids and isinstance(record.get("pid"), int), label + ":distinct process PID")
                pids.add(record.get("pid"))
                audit.check(command_ok(record) and completion.get("returncode") == 0 and completion.get("measurement_command_ok") is True, label + ":process exit and AC control")
                audit.check(["taskset", "-c", "2"] == argv[argv.index("taskset"):argv.index("taskset") + 3], label + ":CPU2 command")
                actual_binary = audit.path(argv[argv.index("taskset") + 3]).resolve()
                audit.check(actual_binary in frozen_binaries, label + ":command binary in frozen provenance")
                for option, value in (("--ring-bytes", workload["ring_bytes"]), ("--block-entries", workload["block_entries"]), ("--seed", workload["seed"])):
                    audit.check(flag(argv, option) == str(value), label + ":command option:" + option)
                if workload["kind"] == "trace":
                    audit.check(audit.path(flag(argv, "--trace")).resolve() == audit.path(workload["trace"]).resolve() and flag(argv, "--anchor-ts") == str(workload["anchor_ts"]), label + ":actual trace/window")
                else:
                    audit.check("--synthetic" in argv and all(flag(argv, option) == str(workload[field]) for option, field in (("--records", "records"), ("--partitions", "partitions"), ("--zipf", "zipf"), ("--run-length", "run_length"))), label + ":synthetic schedule command")
                audit.check(record.get("source_identity") == case["source_identity"], label + ":input identity")
                transport(audit, record, requested, term_hashes, dictionary_path, label)
                output = audit.path(record["output_path"])
                audit.check(output.resolve() == audit.path(flag(argv, "--output")).resolve(), label + ":output command path")
                used_outputs.add(output.resolve())
                actuals = output_rows(output)
                raw = {row["id"]: row for row in actuals if "id" in row}
                audit.check(len(raw) == sum("id" in row for row in actuals) and set(raw) == set(requested), label + ":exact raw request IDs")
                on = prefill(audit, actuals, case, enabled=True, label=label + "/index-on")
                registry_identities[True].add(on.get("registry_identity_sha256"))
                off = None
                if t2_groups:
                    off_record = read_json(block / (process + "-index-off.command.json"))
                    audit.artifacts(off_record, label + ":index-off recorded artifact")
                    audit.check(command_ok(off_record), label + ":index-off process exit/AC")
                    off_argv = off_record["argv"]
                    audit.check(flag(off_argv, "--index-enabled") == "0", label + ":index-off flag")
                    for option in ("--ring-bytes", "--block-entries", "--seed", "--trace", "--anchor-ts", "--records", "--partitions", "--zipf", "--run-length", "--mix"):
                        audit.check(flag(off_argv, option) == flag(argv, option), label + ":identical publisher input option:" + option)
                    audit.check(audit.path(off_argv[off_argv.index("taskset") + 3]).resolve() == actual_binary, label + ":identical publisher binary")
                    off_output = audit.path(off_record["output_path"])
                    audit.check(off_output.resolve() == audit.path(flag(off_argv, "--output")).resolve(), label + ":index-off output command path")
                    with audit.path(flag(off_argv, "--requests")).open(newline="") as stream:
                        audit.check(not list(csv.DictReader(stream, delimiter="\t")), label + ":empty index-off request TSV")
                    used_outputs.add(off_output.resolve())
                    off_values = output_rows(off_output)
                    audit.check(not any("id" in row for row in off_values), label + ":empty index-off request set")
                    off = prefill(audit, off_values, case, enabled=False, label=label + "/index-off")
                    registry_identities[False].add(off.get("registry_identity_sha256"))
                rows = indexes["runs.jsonl"].rows(process)
                by_id = {row["config_id"]: row for row in rows}
                audit.check(len(by_id) == len(rows) and set(by_id) == normalized_ids, label + ":exact normalized configurations")
                readers = indexes["reader-runs.jsonl"].rows(process)
                by_reader = {row["config_id"]: row for row in readers}
                expected_readers = {identity for identity, row in requested.items() if row["exp"] == "T2"}
                audit.check(len(by_reader) == len(readers) and set(by_reader) == expected_readers, label + ":exact retained reader rows")
                if readers:
                    consumed_readers.add(process)
                for identity, request in requested.items():
                    if identity not in raw:
                        continue
                    actual, expected = raw[identity], case["expected"][identity]
                    raw_counts[actual.get("status", "missing")] += 1
                    audit.check(validate(actual, expected)["status"] == "passed", label + ":independent V27/CC-4:" + identity)
                    if actual.get("status") != "invalid_config":
                        audit.check(actual.get("cpu_start") == actual.get("cpu_end") == 2, label + ":actual CPU2:" + identity)
                        audit.check(all(actual.get(field) == value for field, value in {"experiment": request["exp"], "requested_mode": request["mode"], "kernel": request["kernel"], "cache": request["cache_treatment"], "after_seq": request["after_seq"], "readers": request.get("readers", 1)}.items()), label + ":actual request semantics:" + identity)
                    normalized = by_reader.get(identity) if request["exp"] == "T2" else by_id.get(identity)
                    audit.check(normalized is not None, label + ":normalized raw request retained:" + identity)
                    if normalized is None:
                        continue
                    audit.check(validate(normalized, expected)["status"] == "passed" and normalized.get("oracle_validated") is True, label + ":normalized oracle equality:" + identity)
                    audit.check(normalized.get("config", {}).get("terms_sha256") == term_hashes[identity], label + ":normalized subscription hash:" + identity)
                    for field in ("cpu_ns", "wall_ns", "work", "status", "payload_bytes"):
                        if field in actual:
                            audit.check(normalized.get(field) == actual.get(field), label + ":raw-normalized equality:" + identity + "/" + field)
                for row in rows + readers:
                    audit.check(row.get("process_round_id") == process and row.get("process_pid") == record["pid"] and row.get("rep") == completion["rep"] and row.get("warmup") == record["warmup"], label + ":normalized process identity")
                    audit.check(row.get("measurement_command_ok") is True and row.get("status") in STATUSES, label + ":measurement row retained/control")
                    audit.check(row.get("cpu") == 2 and row.get("preset") == "release" and bool(row.get("flags")), label + ":normalized build/affinity")
                    audit.check(row.get("trace_sha256") == case["source_identity"], label + ":normalized input identity")
                    audit.check(row.get("binary_sha256") == frozen_binaries.get(actual_binary), label + ":normalized frozen binary identity")
                for row in rows:
                    normalized_counts[row["status"]] += 1
                for identity, members in t2_groups.items():
                    if identity not in by_id or any(item["id"] not in raw for item in members):
                        continue
                    row = by_id[identity]
                    values = [raw[item["id"]] for item in members]
                    audit.check(sorted(item["reader_index"] for item in members) == list(range(members[0]["reader_count"])), label + ":T2 reader index coverage")
                    audit.check(all(row.get(field) is None for field in STREAM), label + ":T2 has no first-reader stream digest")
                    audit.check(row.get("reader_rows") == len(members) and row.get("reader_validation", {}).get("all_validated") is True, label + ":T2 reader validation coverage")
                    audit.check(audit.path(row["reader_validation"]["rows_reference"]).resolve() == (directory / "reader-runs.jsonl").resolve(), label + ":T2 reader reference")
                    for field in ("out_count", "cpu_ns", "wall_ns", "payload_bytes"):
                        audit.check(row.get(field) == sum(item.get(field, 0) for item in values), label + ":T2 aggregate:" + field)
                    for field in set().union(*(item.get("work", {}).keys() for item in values)):
                        audit.check(row.get("work", {}).get(field) == sum(item.get("work", {}).get(field, 0) for item in values), label + ":T2 all logical work:" + field)
                    expected_status = next((item["status"] for item in values if item["status"] != "ok"), "ok")
                    audit.check(row.get("status") == expected_status, label + ":T2 complete outcome")
                    if on and off:
                        work = row["work"]
                        audit.check(work.get("publish_index_on_cpu_ns") == on["publish_cpu_ns"] and work.get("publish_index_off_cpu_ns") == off["publish_cpu_ns"] and work.get("publish_index_delta_cpu_ns") == on["publish_cpu_ns"] - off["publish_cpu_ns"], label + ":T2 actual signed writer delta")
                        publisher_seconds = (workload["anchor_ts"] - 34200000000000) / 1e9
                        audit.check(work.get("publish_window_market_seconds") == publisher_seconds and work.get("amortized_index_cpu_ns") == (on["publish_cpu_ns"] - off["publish_cpu_ns"]) * row["config"]["market_seconds"] / publisher_seconds, label + ":T2 writer charged once per cohort")
                if any(row["exp"] == "T5" for row in requested.values()):
                    m, alloc = memory(audit, actuals, case, label)
                    for row in rows:
                        if row["exp"] == "T5" and m is not None:
                            audit.check(row.get("memory") == m["memory"] and row.get("gauges") == m["gauges"] and row.get("memory_recount") == m and row.get("allocator") == alloc, label + ":T5 raw memory/allocator retained")
                marker = read_json(block / (process + ".commit.json"))
                audit.check(marker.get("status") == "committed" and marker.get("completion") == completion, label + ":committed journal/state equality")
                audit.check(marker.get("published_counts", {}).get("runs.jsonl") == len(rows) and marker.get("published_counts", {}).get("reader-runs.jsonl") == len(readers), label + ":journal publication counts")
                metadata = indexes["process-metadata.jsonl"].rows(process)
                audit.check(len(metadata) == 1 and metadata[0].get("command") == record, label + ":process metadata command")
                if len(metadata) == 1:
                    compact = [dict({key: value for key, value in item.items() if key != "owner_counts"}, raw_record_path=str(output.resolve())) for item in actuals if "id" not in item]
                    recorded = []
                    for item in metadata[0].get("records", []):
                        canonical = dict(item)
                        if canonical.get("raw_record_path") is not None:
                            canonical["raw_record_path"] = str(audit.path(canonical["raw_record_path"]).resolve())
                        recorded.append(canonical)
                    audit.check(recorded == compact, label + ":raw prefill/memory metadata retained")
            except (KeyError, ValueError, OSError, TypeError, IndexError) as error:
                audit.check(False, label + ":readable complete artifacts", f"{type(error).__name__}: {error}")
            reports.append({"process": process, "workload": workload["id"], "rep": completion["rep"], "status": "passed" if len(audit.failures) == start_failures else "failed"})
        for enabled, identities in registry_identities.items():
            if identities:
                audit.check(len(identities) == 1 and None not in identities, "identical captured registry across processes:" + workload["id"] + ("/on" if enabled else "/off"))
        del case, requested
    completed_ids = {row["id"] for row in completions}
    audit.check(set(indexes["runs.jsonl"].offsets) == completed_ids, "no missing or orphan normalized process rows")
    audit.check(set(indexes["process-metadata.jsonl"].offsets) == completed_ids, "no missing or orphan process metadata")
    audit.check(set(indexes["reader-runs.jsonl"].offsets) == consumed_readers, "no orphan retained reader rows")
    unconfirmed = []
    for path in sorted(directory.glob("*/*.jsonl")):
        if path.resolve() not in used_outputs:
            statuses, malformed = Counter(), 0
            with path.open() as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        if "id" in row:
                            statuses[row.get("status", "missing")] += 1
                    except ValueError:
                        malformed += 1
            unconfirmed.append({"path": str(path), "sha256": audit.sha(path), "request_outcomes": dict(statuses), "malformed_lines": malformed,
                                "status": "unconfirmed attempt, retained; never substituted for a completed process"})
    return {"schema": 1, "status": "passed" if not audit.failures else "failed", "verified_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "plan": str(plan_path), "plan_sha256": audit.sha(plan_path), "directory": str(directory),
            "suite": plan["suite"], "measured_repetitions": count, "saved_warmups_per_configuration": 1,
            "checks": audit.checks, "failures": audit.failures, "completed_processes": reports,
            "raw_request_outcomes_including_warmup": dict(raw_counts), "normalized_outcomes_including_warmup": dict(normalized_counts),
            "unconfirmed_raw_attempts": unconfirmed, "distinct_files_hashed": len(audit.hashes),
            "scope": "Prepared-plan coverage and independently expected saved outcomes; no engine execution, no measurement, and no claim of complete approved matrix unless the supplied prepared plan has separately passed its matrix review"}


def self_test():
    """Temporary format fixtures only: never published as campaign evidence."""
    from tiplog_py.exp.run import normalize_actual, aggregate_t2
    from tiplog_py.exp.hashes import FNV_OFFSET
    with tempfile.TemporaryDirectory(prefix="tiplog-p6-audit-") as temporary:
        directory = Path(temporary)
        trace = directory / "fixture.trace"
        trace.write_bytes(b"explicit synthetic audit fixture")
        config = directory / "fixture.toml"
        config.write_text("# Format fixture; never an experimental configuration.\n")
        binary = directory / "tiplog_bench"
        binary.write_bytes(b"not executable; artifact format fixture only")
        def identity(path):
            return {"path": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        source = identity(trace)["sha256"]
        empty = hashlib.sha256(b"").hexdigest()
        terms = "exact:fixture/a"
        term_hash = hashlib.sha256(terms.encode()).hexdigest()
        requests = []
        for name, experiment in (("success", "T1"), ("expired", "T1"), ("invalid", "T1"),
                                 ("reader0", "T2"), ("reader1", "T2"), ("snapshot", "T5")):
            request = {"id": name, "name": name, "exp": experiment, "terms": terms,
                       "mode": "scan", "kernel": "stdpq", "cache_treatment": "repeat-warm",
                       "after_seq": 0, "readers": 1, "batch": 1024, "ring_bytes": 512,
                       "block_entries": 64, "anchor_ts": 36000000000000, "comparison_id": "fixture"}
            if experiment == "T2":
                request.update(reader_count=2, reader_index=int(name[-1]), market_seconds=10)
            requests.append(request)
        base = {"status": "ok", "out_count": 1, "seq_sha256": hashlib.sha256(b"sequence").hexdigest(),
                "payload_sha256": hashlib.sha256(b"payload").hexdigest(), "sink64": 123,
                "checkpoint": {"after_seq": 3, "next_pos": 72}, "error": None, "upper_seq": 3, "upper_pos": 72}
        expected = {request["id"]: dict(base) for request in requests}
        expected["expired"].update(status="history_expired", out_count=0, seq_sha256=empty,
            payload_sha256=empty, sink64=FNV_OFFSET, checkpoint=None,
            error={"kind": "history_expired", "requested_after": 0, "last_delivered": 0, "oldest_retained": 2})
        expected["invalid"].update(status="invalid_config")
        expected["snapshot"].update(out_count=0, seq_sha256=empty, payload_sha256=empty, sink64=FNV_OFFSET)
        workload = {"id": "fixture-workload", "kind": "trace", "trace": str(trace),
                    "ring_bytes": 512, "block_entries": 64, "seed": 17,
                    "anchor_ts": 36000000000000, "requests": requests}
        case = {"workload": workload, "expected": expected,
                "layout": {"head_pos": 72, "tail_pos": 0, "head_seq": 4, "tail_seq": 1,
                           "retained_data": 3, "pad_bytes": 0, "pad_items": 0},
                "prefill_digest": {"out_count": 3, "sink64": 1234}, "source_identity": source}
        case_path = directory / "prepared.json.gz"
        with gzip.open(case_path, "wt") as stream:
            json.dump(case, stream)
        plan = {"suite": "evaluation", "config": str(config), "config_sha256": identity(config)["sha256"],
                "workloads": [{"id": workload["id"], "path": str(case_path), "sha256": identity(case_path)["sha256"], "requests": len(requests)}]}
        plan_path = directory / "plan.json"
        save(plan_path, plan)
        provenance = {"source_files": [identity(ROOT / path) for path in
            ("py/tiplog_py/exp/run.py", "py/tiplog_py/exp/oracle.py", "CMakeLists.txt")],
            "binaries": [identity(binary)], "inputs": [identity(trace)]}
        save(directory / "provenance.json", provenance)
        state = {"status": "passed", "plan_sha256": identity(plan_path)["sha256"],
                 "repetitions": 10, "excluded_saved_warmups": 1, "completed_processes": []}
        block = directory / workload["id"]
        block.mkdir()
        dictionary = block / "subscription-terms.tsv"
        dictionary.write_text(term_hash + "\t" + terms + "\n")
        normalized_all, readers_all, metadata_all = [], [], []
        for rep in range(-1, 10):
            process = f"fixture-rep{rep}"
            request_path, output = block / (process + ".tsv"), block / (process + ".jsonl")
            request_path.write_text("id\texperiment\tafter_seq\tterms\tmode\tkernel\tcache\tbatch\treaders\n" + "".join(
                "\t".join((r["id"], r["exp"], "0", "@" + term_hash, "scan", "stdpq", "repeat-warm", "1024", "1")) + "\n" for r in requests))
            command = {"argv": ["taskset", "-c", "2", str(binary), "--requests", str(request_path),
                       "--output", str(output), "--term-dictionary", str(dictionary), "--trace", str(trace),
                       "--anchor-ts", str(workload["anchor_ts"]), "--ring-bytes", "512", "--block-entries", "64", "--seed", "17"],
                       "process_id": process, "pid": 5000 + rep, "rep": rep, "warmup": rep == -1,
                       "returncode": 0, "before": {"power": {"ac_online": True}},
                       "after": {"power": {"ac_online": True}}, "observations": [], "output_path": str(output),
                       "requests_sha256": identity(request_path)["sha256"], "source_identity": source,
                       "term_dictionary": dict(identity(dictionary), unique_subscriptions=1)}
            pre = {"kind": "prefill", "status": "ok", "publications": 3, "publish_sink64": 1234,
                   "index_enabled": True, "ring_bytes": 512, "block_entries": 64, "pressure_data_evicted": 0,
                   "pad_bytes_appended": 0, "capacity_and_pressure_data_evicted": 0,
                   "head_seq": 4, "tail_seq": 1, "head_pos": 72, "tail_pos": 0,
                   "cpu_start": 2, "cpu_end": 2, "publish_cpu_ns": 200, "publish_wall_ns": 210,
                   "registry_identity_sha256": "fixture-registry"}
            gauges = dict(allocated_blocks=1, free_blocks=1, allocated_entries=3, live_entries=3,
                          expired_allocated_entries=0, open_slack=61, sealed_partial_slack=0, free_block_slots=64)
            amounts = dict(metadata_reserved_bytes=64, entries_reserved_bytes=512, sealed_flags_reserved_bytes=2,
                           heap_reserved_bytes=0, partition_state_reserved_bytes=64, partition_list_reserved_bytes=4, control_bytes=128)
            amounts["reserved_bytes"] = sum(amounts.values())
            m = dict(kind="memory", status="ok", recount_equal=True, retained_records=3,
                     blocks=2, block_entries=64, head_seq=4, tail_seq=1, head_pos=72, tail_pos=0,
                     gauges=gauges, memory=amounts)
            allocator = dict(kind="allocator", status="ok", stats_equal=True, requested_reserved_bytes=amounts["reserved_bytes"],
                charged_delta_bytes=800, observed_allocator_overhead_bytes=800 - amounts["reserved_bytes"], schedule_rows=3,
                before={"uordblks": 100, "hblkhd": 0}, after={"uordblks": 900, "hblkhd": 0})
            raw = []
            normalized = []
            for request in requests:
                actual = dict(expected[request["id"]], id=request["id"], kind="replay")
                if request["id"] == "invalid":
                    actual = dict(id="invalid", kind="replay", status="invalid_config", reason="fixture rejection")
                else:
                    actual.update(experiment=request["exp"], requested_mode="scan", kernel="stdpq", cache="repeat-warm",
                                  after_seq=0, readers=1, cpu_start=2, cpu_end=2, cpu_ns=10, wall_ns=12,
                                  user_ns=10, system_ns=0, payload_bytes=actual["out_count"], work={"delivered": actual["out_count"], "records_fetched": 1})
                raw.append(actual)
                common = dict(process_round_id=process, process_pid=command["pid"], rep=rep, warmup=rep == -1,
                              cpu=2, preset="release", flags="synthetic fixture only", trace_sha256=source,
                              binary_sha256=identity(binary)["sha256"],
                              measurement_command_ok=True, reader_validation_rows_reference=str(directory / "reader-runs.jsonl"))
                normalized.append(normalize_actual(actual, request, common, expected[request["id"]]))
            all_rows = [pre, *raw, m, allocator]
            output.write_text("".join(json.dumps(row) + "\n" for row in all_rows))
            save(block / (process + ".command.json"), command)
            off_output = block / (process + "-index-off.jsonl")
            off = dict(pre, index_enabled=False, publish_cpu_ns=100)
            off_output.write_text(json.dumps(off) + "\n")
            empty_requests = block / (process + "-index-off.tsv")
            empty_requests.write_text("id\texperiment\tafter_seq\tterms\tmode\tkernel\tcache\tbatch\treaders\n")
            off_argv = list(command["argv"])
            off_argv[off_argv.index("--requests") + 1] = str(empty_requests)
            off_argv[off_argv.index("--output") + 1] = str(off_output)
            off_command = dict(command, argv=off_argv + ["--index-enabled", "0"], output_path=str(off_output),
                               requests_sha256=identity(empty_requests)["sha256"])
            save(block / (process + "-index-off.command.json"), off_command)
            grouped = aggregate_t2(normalized)
            for row in grouped:
                if row["exp"] == "T2":
                    row["work"].update(publish_index_on_cpu_ns=200, publish_index_off_cpu_ns=100,
                        publish_index_delta_cpu_ns=100, publish_window_market_seconds=1800,
                        amortized_index_cpu_ns=100 * 10 / 1800)
                if row["exp"] == "T5":
                    row.update(memory=amounts, gauges=gauges, memory_recount=m, allocator=allocator)
            reader_rows = [row for row in normalized if row["exp"] == "T2"]
            normalized_all += grouped
            readers_all += reader_rows
            metadata_all.append(dict(process_id=process, command=command,
                records=[dict(item, raw_record_path=(os.path.relpath(output, ROOT) if index == 0 else str(output)))
                         for index, item in enumerate((pre, m, allocator))]))
            completion = dict(id=process, workload_id=workload["id"], rep=rep, returncode=0,
                              measurement_command_ok=True, oracle_failures=0, rows=len(raw))
            state["completed_processes"].append(completion)
            save(block / (process + ".commit.json"), dict(status="committed", completion=completion,
                published_counts={"runs.jsonl": len(grouped), "reader-runs.jsonl": len(reader_rows), "process-metadata.jsonl": 1}))
        for filename, rows in (("runs.jsonl", normalized_all), ("reader-runs.jsonl", readers_all), ("process-metadata.jsonl", metadata_all)):
            (directory / filename).write_text("".join(json.dumps(row) + "\n" for row in rows))
        save(directory / "state.json", state)
        result = audit_session(plan_path, directory)
        if result["status"] != "passed":
            raise AssertionError(json.dumps(result["failures"], indent=2))
        failures_detected = []
        # Preserve every expiry/invalid case while accepting valid format fixtures.
        assert result["raw_request_outcomes_including_warmup"]["history_expired"] == 11
        assert result["raw_request_outcomes_including_warmup"]["invalid_config"] == 11
        target = block / "fixture-rep0.jsonl"
        original = target.read_text()
        values = output_rows(target)
        next(row for row in values if row.get("id") == "success")["sink64"] += 1
        target.write_text("".join(json.dumps(row) + "\n" for row in values))
        assert audit_session(plan_path, directory)["status"] == "failed"
        failures_detected.append("raw output digest tamper")
        target.write_text(original)
        rows_path = directory / "runs.jsonl"
        saved_rows = rows_path.read_text()
        rows = output_rows(rows_path)
        next(row for row in rows if row["exp"] == "T2")["sink64"] = 123
        rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        assert audit_session(plan_path, directory)["status"] == "failed"
        failures_detected.append("misleading first-reader group digest")
        rows_path.write_text(saved_rows)
        dictionary.write_text(term_hash + "\t" + terms + "-tampered\n")
        assert audit_session(plan_path, directory)["status"] == "failed"
        failures_detected.append("subscription dictionary semantic/hash tamper")
        dictionary.write_text(term_hash + "\t" + terms + "\n")
        values = output_rows(target)
        next(row for row in values if row.get("kind") == "allocator")["charged_delta_bytes"] += 1
        target.write_text("".join(json.dumps(row) + "\n" for row in values))
        assert audit_session(plan_path, directory)["status"] == "failed"
        failures_detected.append("allocator arithmetic tamper")
        target.write_text(original)
        original_state = dict(state)
        state["completed_processes"] = state["completed_processes"][:-1]
        save(directory / "state.json", state)
        assert audit_session(plan_path, directory)["status"] == "failed"
        failures_detected.append("missing required process repetition")
        state = original_state
        save(directory / "state.json", state)
        duplicate = read_json(block / "fixture-rep1.command.json")
        duplicate["pid"] = read_json(block / "fixture-rep0.command.json")["pid"]
        save(block / "fixture-rep1.command.json", duplicate)
        assert audit_session(plan_path, directory)["status"] == "failed"
        failures_detected.append("reused process PID")
        print(json.dumps({"status": "passed", "fixture_scope": "temporary synthetic artifact validation only; no experiments executed", "successful_fixture_processes": 11, "successful_fixture_checks": result["checks"], "tampering_rejected": failures_detected}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.plan is None or args.directory is None:
        parser.error("--plan and --directory are required")
    try:
        result = audit_session(args.plan, args.directory, args.repetitions)
    except Exception as error:
        result = {"schema": 1, "status": "failed", "suite": "unreadable or incomplete evidence",
                  "checks": 0, "measured_repetitions": args.repetitions,
                  "distinct_files_hashed": 0, "plan": str(args.plan), "directory": str(args.directory),
                  "failures": [{"check": "readable complete audit prerequisites", "detail": f"{type(error).__name__}: {error}"}]}
    result["auditor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save(args.directory / "independent-audit.json", result)
    print(json.dumps({key: result[key] for key in ("status", "suite", "checks", "measured_repetitions", "distinct_files_hashed", "failures")}))
    return result["status"] != "passed"


if __name__ == "__main__":
    raise SystemExit(main())
