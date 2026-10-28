#!/usr/bin/env python3
"""Extract T5 historical allocation peaks from accepted measured process records.

Uses evaluation state to select accepted attempts, excluding saved warm-ups and
unconfirmed/interrupted raw files. Never executes a benchmark or mutates input.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics


def identity(path):
    path = Path(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def stats(values):
    return {"n": len(values), "min": min(values),
            "median": statistics.median(values), "max": max(values)}


def build(directory):
    directory = Path(directory)
    state_path = directory / "state.json"
    state = json.loads(state_path.read_text())
    if state["status"] != "passed" or state["repetitions"] != 20:
        raise ValueError("requires accepted completed20-round evaluation state")
    groups = defaultdict(list)
    for row in state["completed_processes"]:
        if row["workload_id"].startswith("memory-") and row["rep"] >= 0:
            if row.get("oracle_failures", 0) or not row.get("measurement_command_ok") or row["returncode"]:
                raise ValueError("failed memory process is not accepted")
            groups[row["workload_id"]].append(row)
    expected = {f"memory-B{block}-A{anchor}" for block in (64, 256, 1024, 4096)
                for anchor in (34500000000000, 35100000000000, 36000000000000)}
    if set(groups) != expected:
        raise ValueError("incomplete approved12-workload memory matrix")
    workloads = []
    for name, rows in sorted(groups.items()):
        if len(rows) != 20 or {row["rep"] for row in rows} != set(range(20)):
            raise ValueError(f"{name}: missing or duplicate repetition")
        if len({row["id"] for row in rows}) != 20:
            raise ValueError(f"{name}: duplicate accepted attempt")
        records, raw_inputs, commands = [], [], []
        for row in sorted(rows, key=lambda item: item["rep"]):
            raw = directory / name / (row["id"] + ".jsonl")
            values = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
            memory = [value for value in values if value.get("kind") == "memory"]
            if len(memory) != 1:
                raise ValueError(f"{row['id']}: expected one memory record")
            value = memory[0]
            if value["status"] != "ok" or value["recount_equal"] is not True:
                raise ValueError("failed memory/recount outcome")
            current, peak, capacity = (value["gauges"]["allocated_blocks"],
                                       value["allocated_high_water"], value["blocks"])
            if not 0 <= current <= peak <= capacity:
                raise ValueError("allocation high-water outside pool bounds")
            command_path = directory / name / (row["id"] + ".command.json")
            command = json.loads(command_path.read_text())
            argv = command["argv"]
            block = int(argv[argv.index("--block-entries") + 1])
            anchor = int(argv[argv.index("--anchor-ts") + 1])
            if name != f"memory-B{block}-A{anchor}" or block != value["block_entries"]:
                raise ValueError("raw/command/workload block or anchor disagreement")
            records.append({"rep": row["rep"], "process_id": row["id"],
                            "block_entries": block, "anchor_ts": anchor,
                            "allocated_blocks": current, "allocated_high_water": peak,
                            "pool_blocks": capacity, "live_entries": value["gauges"]["live_entries"],
                            "requested_reserved_bytes": value["memory"]["reserved_bytes"]})
            raw_inputs.append(identity(raw))
            commands.append(identity(command_path))
        workloads.append({"workload_id": name, "block_entries": records[0]["block_entries"],
                          "anchor_ts": records[0]["anchor_ts"],
                          "allocated_high_water": stats([value["allocated_high_water"] for value in records]),
                          "allocated_blocks": stats([value["allocated_blocks"] for value in records]),
                          "pool_blocks": stats([value["pool_blocks"] for value in records]),
                          "records": records, "raw_inputs": raw_inputs, "command_inputs": commands})
    return {"schema": 1, "status": "passed", "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "state": identity(state_path), "script": identity(Path(__file__)),
            "measured_processes": 240, "workloads": workloads,
            "scope": "Historical peak allocated index blocks over each actual publication prefill. Counts are not resident bytes; fixed whole-pool requested reservation is a separate quantity. Accepted state selects attempts, with warm-ups and unconfirmed attempts excluded."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/derived/t5-high-water.json"))
    args = parser.parse_args()
    result = build(args.directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "passed", "workloads": len(result["workloads"]),
                      "measured_processes": result["measured_processes"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
