#!/usr/bin/env python3
"""Predeclare and execute a bounded, source-bound F01 replay polling study.

The study intentionally covers dimensions marginally rather than taking their
full Cartesian product. Every timed job runs in three fresh tool processes.
Original outputs are preserved; a separate derived normalization changes only
the repetition label from zero to the process-repetition index.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from check_remediation import input_sets
import f01_summary
from build_provenance import capture_build, verify_build, validate_configuration

ROOT = Path(__file__).resolve().parents[1]
ALL_BUDGETS = "legacy,unlimited,1,8,32,128,512,2048"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def write_new(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def arguments(**values):
    return list(itertools.chain.from_iterable(("--" + key.replace("_", "-"), str(value)) for key, value in values.items()))


def rows_for(argv):
    values = dict(zip(argv[::2], argv[1::2], strict=True))
    result = int(values["--reps"])
    for key in ("--cases", "--shapes", "--partitions", "--candidate-every", "--modes", "--kernels", "--budgets", "--schedules"):
        result *= len(values[key].split(","))
    return result


def declared_identities(argv):
    values = dict(zip(argv[::2], argv[1::2], strict=True))
    dimensions = (("case", "--cases", str), ("shape", "--shapes", str),
                  ("configured_partitions", "--partitions", int), ("candidate_every", "--candidate-every", int),
                  ("mode", "--modes", str), ("kernel", "--kernels", str),
                  ("budget", "--budgets", str), ("schedule", "--schedules", str))
    fields = [field for field, _, _ in dimensions] + ["repetition"]
    choices = [[convert(value) for value in values[option].split(",")] for _, option, convert in dimensions]
    choices.append(list(range(int(values["--reps"]))))
    fixed = {"records": int(values["--records"]), "seed": int(values["--seed"]), "max_outputs": int(values["--max-outputs"])}
    keys = tuple(sorted((*fields, *fixed)))
    expected = {tuple((dict(zip(fields, combination, strict=True)) | fixed)[key] for key in keys) for combination in itertools.product(*choices)}
    return keys, expected


def require_declared_rows(argv, rows):
    fields, expected = declared_identities(argv)
    actual = [tuple(row[field] for field in fields) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("raw rows differ from the exact predeclared arm identities")


def plan():
    common = dict(candidate_every="1", kernels="stdpq", schedules="round-robin", max_outputs=1, seed=20261026, reps=1)
    jobs = []

    def add(name, purpose, **options):
        args = arguments(**(common | options))
        jobs.append({"id": name, "purpose": purpose, "argv": args, "process_repetitions": 3,
                     "expected_original_rows_per_process": rows_for(args), "expected_rows": 3 * rows_for(args)})

    add("demo-1m", "Literal million-candidate before/after demonstration, with no match and one final match.",
        records=1000000, cases="no-match,late-match", shapes="small", partitions="1", modes="scan,indexed,auto", budgets="legacy,unlimited,1,1000")
    add("pareto-100k", "Inspection-budget sweep for rejecting and sparse readers, with K1 and K4.",
        records=100000, cases="no-match,sparse", shapes="small", partitions="1,4", modes="scan,indexed,auto", budgets=ALL_BUDGETS)
    add("dense-throughput", "All selected DATA matches; a large output allowance exposes total throughput cost.",
        records=100000, cases="dense", shapes="small", partitions="1,4", modes="scan,indexed,auto", budgets=ALL_BUDGETS, max_outputs=4096)
    add("setup-stress", "Repeated cursor preparation and Auto fallback at K64/256/4096; small static range keeps work bounded.",
        records=1000, cases="no-match", shapes="small", partitions="64,256,4096", modes="scan,indexed,auto", kernels="stdpq,quad", budgets="legacy,unlimited,1,128,2048")
    add("record-shapes-kernels", "Nonuniform payloads, a wrap/PAD, background partitions and Auto-to-Indexed across every merge kernel.",
        records=4096, cases="no-match,late-match", shapes="fixed,variable,wrapped-variable", partitions="4", candidate_every="1,8", modes="indexed,auto", kernels="stdpq,binheap,quad,loser", budgets="legacy,unlimited,1,32,512")
    add("scheduling-control", "Round-robin versus immediately draining the same reader; budget alone does not schedule other work.",
        records=200000, cases="no-match", shapes="small", partitions="1", modes="scan,indexed", budgets="legacy,unlimited,1,128,2048", schedules="round-robin,immediate-redrain")
    preflight = arguments(**(common | dict(records=1000, cases="no-match", shapes="small", partitions="8192,12288", modes="indexed", budgets="unlimited", reps=3)))
    return {
        "schema": "tiplog.f01.study-plan.v1", "created_utc": now(), "status": "predeclared-before-study-timing",
        "protocol": "results/f01/protocol.json", "protocol_sha256": sha(ROOT / "results/f01/protocol.json"),
        "scope": "Static retained Replay only. Three fresh process repetitions per timed job. Fixture seed and each process's initial arm order are identical; no cache flush, inferential confidence interval, quiet-host or hard-latency claim. Work/accounting and eventual output equivalence are hard checks.",
        "normalization": "Preserve every original --reps1 JSONL. A recorded normalizer creates derived JSONL changing ONLY repetition0 to process repetition0/1/2; external normalization.json binds input/output paths and hashes, direct command record, tool repetition and process repetition. Summary consumes derived copies, never rewrites original tool output.",
        "timed_jobs": jobs, "expected_timed_rows": sum(job["expected_rows"] for job in jobs),
        "preflight": {"id": "resource-boundary", "argv": preflight, "expected_rows": rows_for(preflight),
                      "expected_status_by_partitions": {"8192": "ok", "12288": "infeasible"},
                      "scope": "Separate resource control, excluded from timing summary and accepted benchmark raw. This brackets tested stress points, not the exact highest feasible K."},
        "analysis": {"summarizer": "scripts/f01_summary.py", "summarizer_sha256": sha(ROOT / "scripts/f01_summary.py"),
                     "contracts": "results/f01/check_tool.py", "contracts_sha256": sha(ROOT / "results/f01/check_tool.py"),
                     "pairing": "Within each same-input group, pair each budget with legacy by fresh process repetition label; summarize ratios and per-repetition percentiles using medians, not pooled calls."},
        "coverage": {"budgets": ALL_BUDGETS.split(","), "extra_demo_budget": "1000", "cases": ["no-match", "late-match", "sparse", "dense"],
                     "shapes": ["small", "fixed", "variable", "wrapped-variable"], "modes": ["scan", "indexed", "auto"],
                     "kernels": ["stdpq", "binheap", "quad", "loser"], "partitions": [1, 4, 64, 256, 4096],
                     "schedules": ["round-robin", "immediate-redrain"], "candidate_every": [1, 8], "repetition_labels": [0, 1, 2]},
    }


def host_observation():
    observation = {"utc": now(), "platform": platform.platform(), "uname": list(platform.uname()),
                   "load_average": list(os.getloadavg()), "allowed_cpus": sorted(os.sched_getaffinity(0)), "cpu_count": os.cpu_count()}
    for name in ("/proc/stat", "/proc/meminfo"):
        try:
            observation[Path(name).name] = Path(name).read_text()
        except OSError as error:
            observation[Path(name).name] = {"unavailable": str(error)}
    observation["cpu_frequency_observations"] = {}
    for cpu in observation["allowed_cpus"][:8]:
        values = {}
        for field in ("scaling_cur_freq", "scaling_governor", "scaling_min_freq", "scaling_max_freq"):
            try:
                values[field] = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/{field}").read_text().strip()
            except OSError:
                values[field] = None
        observation["cpu_frequency_observations"][str(cpu)] = values
    return observation


def source_binding(freeze_path):
    frozen = json.loads(freeze_path.read_text())
    mismatches = [name for name, expected in frozen["compiled_sources"].items() if not (ROOT / name).is_file() or sha(ROOT / name) != expected]
    if mismatches:
        raise ValueError(f"compiled source differs from freeze: {mismatches[:5]}")
    current = input_sets()
    if current["cpp"] != frozen["cpp_input_set"]:
        raise ValueError("current C++ input set differs from source freeze")
    return frozen, current


def load_summary_module(path):
    # Historical plans still bind their original analysis file, while every
    # new execution also receives the maintained independent fixture checks.
    if path.resolve() not in {(ROOT / 'results/f01/summarize.py').resolve(),
                              (ROOT / 'scripts/f01_summary.py').resolve()}:
        raise ValueError('unknown F01 analysis implementation')
    return f01_summary


def normalize(args):
    declaration = json.loads(args.mapping.read_text())
    if declaration["schema"] != "tiplog.f01.normalization-plan.v1":
        raise ValueError("unknown normalization plan")
    normalized = {"schema": "tiplog.f01.repetition-normalization.v1", "rule": "Only repetition changes: tool repetition0 becomes fresh process repetition0/1/2. All other row values are identical to the preserved original.",
                  "mapping_plan": relative(args.mapping), "mapping_plan_sha256": sha(args.mapping), "files": []}
    module = load_summary_module(ROOT / "results/f01/summarize.py")
    for entry in declaration["files"]:
        source, output = ROOT / entry["input"], ROOT / entry["output"]
        allowed = (ROOT / "results/f01", ROOT / "build/f01")
        if not any(source.resolve().is_relative_to(path) for path in allowed) or not any(output.resolve().is_relative_to(path) for path in allowed):
            raise ValueError("normalization input/output escapes F01 namespace")
        if sha(source) != entry["input_sha256"] or entry["tool_repetition"] != 0 or entry["process_repetition"] not in (0, 1, 2):
            raise ValueError("normalization source identity/repetition mismatch")
        count = 0
        with source.open() as original, output.open("x") as derived:
            for line in original:
                row = json.loads(line)
                module.validate(row)
                if row["repetition"] != 0:
                    raise ValueError("original tool row is not repetition0")
                row["repetition"] = entry["process_repetition"]
                derived.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
                count += 1
        normalized["files"].append(entry | {"output_sha256": sha(output), "rows": count})
    write_new(args.output, normalized)
    print(json.dumps({"status": "passed", "files": len(normalized["files"]), "rows": sum(item["rows"] for item in normalized["files"])}))
    return 0


def execute(args):
    specification = json.loads(args.plan.read_text())
    if specification["schema"] != "tiplog.f01.study-plan.v1":
        raise ValueError("unknown study plan")
    protocol = ROOT / specification["protocol"]
    if sha(protocol) != specification["protocol_sha256"]:
        raise ValueError("protocol changed after plan declaration")
    for field in ("summarizer", "contracts"):
        if sha(ROOT / specification["analysis"][field]) != specification["analysis"][field + "_sha256"]:
            raise ValueError(f"{field} changed after plan declaration")
    frozen, _ = source_binding(args.freeze)
    build_record = json.loads(args.build_record.read_text())
    if build_record.get("status") != "passed" or build_record.get("exit_code") != 0:
        raise ValueError("successful final Release build record required")
    if any(build_record.get(field, {}).get("cpp") != frozen["cpp_input_set"] for field in ("input_sets_before", "input_sets_after")):
        raise ValueError("Release build record differs from frozen C++ sources")
    build_argv = build_record.get("argv", [])
    if (build_argv[:4] != ['cmake', '--build', '--preset', 'release']
            or build_record.get('build_execution') != {'preset':'release','kind':'build','full_build':True}
            or any(value in build_argv[4:] for value in ('--target', '-t', '--'))):
        raise ValueError("record does not describe a full Release preset build")
    if sha(ROOT / build_record["log"]) != build_record["log_sha256"]:
        raise ValueError("Release build log identity mismatch")
    snapshot = build_record.get('build_provenance')
    verify_build(snapshot, ROOT, 'release', frozen['cpp_input_set'])
    validate_configuration(snapshot, ROOT, 'release')
    binary = args.binary.resolve()
    if not binary.is_relative_to(ROOT / "build/release"):
        raise ValueError("study binary must be inside build/release")
    binary_sha = sha(binary)
    destination = args.destination.resolve()
    if not destination.is_relative_to(ROOT / "results/f01"):
        raise ValueError("study destination must be under results/f01")
    destination.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    module = load_summary_module(ROOT / specification["analysis"]["summarizer"])
    binding = {"binary": relative(binary), "binary_sha256": binary_sha,
               "source_freeze": relative(args.freeze), "source_freeze_sha256": sha(args.freeze),
               "cpp_input_set": frozen["cpp_input_set"], "protocol": relative(protocol), "protocol_sha256": sha(protocol),
               "plan": relative(args.plan), "plan_sha256": sha(args.plan), "runner": relative(__file__), "runner_sha256": sha(__file__),
               "build_record": relative(args.build_record), "build_record_sha256": sha(args.build_record)}
    manifest = {"schema": "tiplog.f01.study-run.v1", "status": "running", "started_utc": now(),
                "binding": binding, "records": [], "original_raw": [], "raw": [], "preflight_records": [], "preflight_raw": [], "jobs": []}
    manifest_path = destination / "manifest.json"
    write_new(manifest_path, manifest)

    def save_manifest():
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")

    def run_command(label, command, raw=None):
        source_binding(args.freeze)
        if sha(binary) != binary_sha:
            raise ValueError("benchmark binary changed during study")
        record_path = destination / (label + ".record.json")
        log = destination / (label + ".log")
        record = {"label": label, "argv": command, "cwd": str(ROOT), "started_utc": now(), "status": "running",
                  "input_sets_before": input_sets(), "log": relative(log), "binding": binding,
                  "binary_sha256": binary_sha, "environment": {key: environment.get(key) for key in ("ASAN_OPTIONS", "UBSAN_OPTIONS", "PYTHONDONTWRITEBYTECODE")},
                  "host_before": host_observation()}
        record['build_artifacts_before'] = capture_build(ROOT, 'release', frozen['cpp_input_set'])
        if record['build_artifacts_before'] != snapshot:
            raise ValueError('study artifacts differ from the source-bound Release build')
        write_new(record_path, record)
        start = time.monotonic()
        with log.open("x") as output:
            try:
                code = subprocess.run(command, cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT).returncode
            except OSError as error:
                output.write(str(error) + "\n")
                code = 127
        record.update(exit_code=code, elapsed_seconds=time.monotonic() - start, finished_utc=now(),
                      status="passed" if code == 0 else "failed", log_sha256=sha(log), input_sets_after=input_sets(), host_after=host_observation())
        record['build_artifacts_after'] = capture_build(ROOT, 'release', frozen['cpp_input_set'])
        if record['build_artifacts_after'] != snapshot:
            record.update(exit_code=125, status='failed', provenance_error='study build artifacts changed during execution')
        if raw is not None and raw.exists():
            record.update(raw_output=relative(raw), raw_sha256=sha(raw))
        record_path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
        source_binding(args.freeze)
        if sha(binary) != binary_sha:
            raise ValueError("benchmark binary changed during study")
        return record_path, record

    try:
        raw_paths = []
        normalization_entries = []
        for job in specification["timed_jobs"]:
            job_records, job_originals = [], []
            for process_repetition in range(job["process_repetitions"]):
                label = f"{job['id']}-process-{process_repetition:02}"
                raw = destination / (label + ".jsonl")
                command = [str(binary), *job["argv"], "--output", str(raw)]
                record_path, record = run_command(label, command, raw)
                manifest["records"].append(relative(record_path))
                manifest["original_raw"].append(relative(raw))
                job_records.append(relative(record_path))
                job_originals.append(relative(raw))
                save_manifest()
                if record["exit_code"] != 0:
                    raise ValueError(f"timed job failed: {label}; raw outcomes retained")
                result = module.summarize([raw])
                require_declared_rows(job["argv"], [json.loads(line) for line in raw.read_text().splitlines()])
                if result["validated_rows"] != job["expected_original_rows_per_process"] or any(arm["repetition_labels"] != [0] for arm in result["arms"]):
                    raise ValueError(f"timed job row/repetition mismatch: {label}")
                normalized = destination / (label + ".normalized.jsonl")
                normalization_entries.append({"input": relative(raw), "input_sha256": sha(raw), "output": relative(normalized),
                                              "record": relative(record_path), "tool_repetition": 0, "process_repetition": process_repetition})
                raw_paths.append(normalized)
                print(json.dumps({"job": label, "status": "passed", "rows": result["validated_rows"], "elapsed_seconds": record["elapsed_seconds"]}), flush=True)
            manifest["jobs"].append({"id": job["id"], "status": "passed", "rows": job["expected_rows"], "records": job_records, "original_raw": job_originals})
            save_manifest()
        normalization_plan = destination / "normalization-plan.json"
        write_new(normalization_plan, {"schema": "tiplog.f01.normalization-plan.v1", "files": normalization_entries})
        normalization = destination / "normalization.json"
        normalization_record, record = run_command("normalization", [sys.executable, str(ROOT / "scripts/run_f01_study.py"), "normalize", "--mapping", str(normalization_plan), "--output", str(normalization)])
        manifest.update(normalization=relative(normalization), normalizer_record=relative(normalization_record), raw=[relative(path) for path in raw_paths])
        if record["exit_code"] != 0:
            raise ValueError("repetition normalization failed")
        save_manifest()
        control = specification["preflight"]
        raw = destination / (control["id"] + ".jsonl")
        record_path, record = run_command(control["id"], [str(binary), *control["argv"], "--output", str(raw)], raw)
        manifest["preflight_records"].append(relative(record_path))
        manifest["preflight_raw"].append(relative(raw))
        save_manifest()
        rows = [json.loads(line) for line in raw.read_text().splitlines()]
        require_declared_rows(control["argv"], rows)
        if record["exit_code"] != 1 or len(rows) != control["expected_rows"] or any(row["status"] != control["expected_status_by_partitions"][str(row["configured_partitions"])] for row in rows):
            raise ValueError("resource preflight differs from declared expected outcomes")
        for row in rows:
            if row["status"] == "ok":
                module.validate(row)
        manifest["resource_preflight"] = {"status": "passed", "expected_nonzero_exit": True, "outcomes": [{key: row[key] for key in ("configured_partitions", "repetition", "status")} for row in rows]}
        summary = destination / "summary.json"
        result = module.summarize(raw_paths)
        if result["validated_rows"] != specification["expected_timed_rows"]:
            raise ValueError("total study row count mismatch")
        write_new(summary, result)
        manifest["summary"] = relative(summary)
        contracts = destination / "contracts.json"
        contract_matrix = next(path for path in raw_paths if path.name.startswith("pareto-100k-process-00"))
        contracts_record, record = run_command("contracts", [sys.executable, str(ROOT / specification["analysis"]["contracts"]), "--binary", str(binary), "--matrix", str(contract_matrix), "--output", str(contracts)])
        manifest["contracts"] = relative(contracts)
        manifest["contract_record"] = relative(contracts_record)
        if record["exit_code"] != 0:
            raise ValueError("benchmark contract check failed")
        files = [path for path in destination.iterdir() if path.is_file() and path != manifest_path]
        manifest.update(status="passed", finished_utc=now(), validated_rows=result["validated_rows"], arm_groups=len(result["arms"]),
                        evidence={relative(path): sha(path) for path in sorted(files)})
        save_manifest()
        print(json.dumps({"status": "passed", "manifest": relative(manifest_path), "rows": result["validated_rows"], "arms": len(result["arms"])}))
        return 0
    except Exception as error:
        manifest.update(status="failed", finished_utc=now(), error=str(error))
        save_manifest()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--freeze", type=Path, required=True)
    run.add_argument("--build-record", type=Path, required=True)
    run.add_argument("--binary", type=Path, default=ROOT / "build/release/tiplog_poll_bench")
    run.add_argument("--destination", type=Path, required=True)
    normalizer = commands.add_parser("normalize")
    normalizer.add_argument("--mapping", type=Path, required=True)
    normalizer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        target = args.output.resolve()
        if not target.is_relative_to(ROOT / "results/f01"):
            parser.error("plan must be under results/f01")
        target.parent.mkdir(parents=True, exist_ok=True)
        result = plan()
        write_new(target, result)
        print(json.dumps({"plan": relative(target), "sha256": sha(target), "expected_timed_rows": result["expected_timed_rows"], "preflight_rows": result["preflight"]["expected_rows"]}))
        return 0
    if args.command == "normalize":
        return normalize(args)
    return execute(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"F01 study: {error}", file=sys.stderr)
        raise SystemExit(1)
