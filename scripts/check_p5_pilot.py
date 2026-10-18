#!/usr/bin/env python3
"""Independently audit saved P5 pilot artifacts; never execute a benchmark.

The M2 sequence-sink check is O(64) per invocation, independent of its adaptive
publication count. --self-test checks that algebra against a literal recurrence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parent.parent
MASK = (1 << 64) - 1
INITIAL = 14695981039346656037
OUTPUTS = 1 << 22
SEED = 20191230


def rotl(value: int, amount: int) -> int:
    amount %= 64
    return ((value << amount) | (value >> ((64 - amount) % 64))) & MASK


def xor_zero_through(value: int) -> int:
    if value < 0:
        return 0
    return (value, 1, value + 1, 0)[value % 4]


def sequence_digest(start: int, count: int, initial: int = INITIAL) -> int:
    """Closed form of h <- rotl(h,7) XOR seq for consecutive uint64 seqs.

After n steps, seq j has rotation 7*(n-1-j). Group j by residue mod64:
rotations agree inside each group. The sequence's low6 bits are constant in
that group, while its high58 bits form a consecutive range with O(1) XOR.
No sequence wrap is permitted, matching the engine's checked sequence contract.
"""
    if start < 0 or count < 0 or initial < 0 or initial > MASK or start > MASK:
        raise ValueError("unsigned sequence/count/initial required")
    if count and start + count - 1 > MASK:
        raise ValueError("sequence range wraps uint64")
    result = rotl(initial, 7 * count)
    for residue in range(min(64, count)):
        first = start + residue
        members = (count - 1 - residue) // 64 + 1
        high = first >> 6
        high_xor = xor_zero_through(high + members - 1) ^ xor_zero_through(high - 1)
        group_xor = (high_xor << 6) ^ ((first & 63) if members % 2 else 0)
        result ^= rotl(group_xor, 7 * (count - 1 - residue))
    return result


def literal_digest(start: int, count: int, initial: int = INITIAL) -> int:
    result = initial
    for seq in range(start, start + count):
        result = rotl(result, 7) ^ seq
    return result


def self_test() -> dict[str, object]:
    cases = 0
    for count in (0, 1, 2, 7, 63, 64, 65, 127, 128, 129, 4095, 4096, 4097):
        for candidate in (0, 1, 62, 63, 64, 65, (1 << 51) - 65, MASK - count):
            start = max(0, candidate)
            assert sequence_digest(start, count) == literal_digest(start, count), (start, count)
            cases += 1
    rng = random.Random(20191230)
    for _ in range(512):
        count = rng.randrange(2049)
        start = rng.randrange(MASK - count + 1)
        initial = rng.getrandbits(64)
        assert sequence_digest(start, count, initial) == literal_digest(start, count, initial)
        cases += 1
    # Wide counts never use a linear loop. Composition checks arithmetic beyond
    # floating-point's exact-integer range and near the uint64 sequence boundary.
    for _ in range(128):
        count = rng.randrange(1 << 60)
        split = rng.randrange(count + 1)
        start = rng.randrange(MASK - count + 1)
        initial = rng.getrandbits(64)
        left = sequence_digest(start, count, initial)
        right = sequence_digest(start + split, count - split,
                                sequence_digest(start, split, initial))
        assert left == right
        cases += 1
    for start, count in ((MASK, 2), (-1, 1), (0, -1)):
        try:
            sequence_digest(start, count)
        except ValueError:
            cases += 1
        else:
            raise AssertionError("invalid sequence range accepted")
    return {"status": "passed", "cases": cases, "random_seed": 20191230,
            "checks": ["literal recurrence on small/random/carry/rotation/uint64 boundaries",
                       "wide-count concatenation identity", "invalid range rejection"],
            "scope": "Digest algebra verification only; no benchmark execution."}


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            result.update(block)
    return result.hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def load_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, object]] = []
        self.errors: list[str] = []

    def check(self, condition: bool, label: str, **details: object) -> None:
        self.checks.append({"check": label, "status": "passed" if condition else "failed", **details})
        if not condition:
            self.errors.append(label)

    def identity(self, entry: dict[str, object]) -> None:
        path = ROOT / entry["path"]
        self.check(path.is_file() and path.stat().st_size == entry["bytes"] and
                   sha(path) == entry["sha256"], f"identity: {entry['path']}")


def functional_records(pattern: str) -> list[dict[str, object]]:
    matches = sorted((ROOT / "results/p5").glob(pattern))
    if not matches:
        raise RuntimeError(f"missing independent pre-pilot functional evidence: {pattern}")
    return load_lines(matches[-1])


def audit_m1(audit: Audit, directory: Path, rows: list[dict[str, object]],
             invocations: list[dict[str, object]]) -> None:
    reference = functional_records("M1-full-pilot-functional-*.log")
    expected = {row["input"]["profile"] + "/" + row["input"]["kernel"]: row
                for row in reference if row.get("status") == "passed"}
    inputs = load_lines(directory / "inputs.jsonl")
    audit.check(len(expected) == 15, "M1 independently verified functional case count")
    audit.check(len(inputs) == len(invocations), "M1 one input manifest per logged invocation")
    for ordinal, (item, invocation) in enumerate(zip(inputs, invocations)):
        name = item["profile"] + "/" + item["kernel"]
        original = expected.get(name)
        audit.check(original is not None and invocation["profile"] == name,
                    f"M1 invocation {ordinal}: functional profile identity")
        audit.check(item.get("outputs") == OUTPUTS and item.get("requested_k") == 64 and
                    item.get("seed") == SEED and item.get("diagnostic") is False,
                    f"M1 invocation {ordinal}: full selected workload")
        if original is not None:
            for field in ("input_hash_hex", "expected_hash_hex", "touch_initialization_hash_hex",
                          "touch_initialized_bytes", "touch_address_span_bytes",
                          "touch_distinct_64B_line_bytes", "touch_loaded_bytes"):
                audit.check(item.get(field) == original["input"].get(field),
                            f"M1 invocation {ordinal}: {field}")
        audit.check(invocation.get("outputs_per_iteration") == OUTPUTS and
                    int(invocation["digest_hex"], 16) == int(item["expected_hash_hex"], 16),
                    f"M1 invocation {ordinal}: count and independent output digest")
    for row in rows:
        label = json.loads(row["label"])
        name = row["run_name"]
        audit.check(name in expected and label["expected_hash_hex"] ==
                    expected[name]["input"]["expected_hash_hex"] and
                    label["input_hash_hex"] == expected[name]["input"]["input_hash_hex"],
                    f"M1 repetition {name}/{row['repetition_index']}: label identities")


def audit_m2(audit: Audit, label: str, context: dict[str, object],
             invocations: list[dict[str, object]]) -> None:
    block_entries = int(label.split("B")[1])
    profile = f"M2/payload_64/P100/uniform/B{block_entries}"
    reference = functional_records("M2-full-matrix-functional-*.log")
    expected = next(row for row in reference if row["profile"] == profile)
    audit.check(context.get(profile + "/input_schedule_fnv_hex") == expected["input_schedule_fnv_hex"],
                f"{label}: independent functional schedule identity")
    audit.check(context.get("input_seed") == str(SEED), f"{label}: input seed")
    for row in invocations:
        ordinal = row["invocation"]
        details = row["details"]
        count = int(row["iterations"]) * int(row["outputs_per_iteration"])
        start = int(details["start_head_seq"])
        expected_digest = sequence_digest(start, count)
        audit.check(row["profile"] in (profile + "/index_off", profile + "/index_on") and
                    row["outputs_per_iteration"] == 4096,
                    f"{label} invocation {ordinal}: profile/batch identity")
        audit.check(int(details["end_head_seq"]) - start == count and
                    int(row["digest_hex"], 16) == expected_digest,
                    f"{label} invocation {ordinal}: independent adaptive prefix count/digest",
                    count=count, expected_digest_hex=f"{expected_digest:x}")
        audit.check(details["prefill_publishes"] == start - 1 and
                    details["prefill_data_evicted"] > 0 and
                    details["prefill_pressure_data_evicted"] == 0 and
                    details["end_pressure_data_evicted"] == 0,
                    f"{label} invocation {ordinal}: actual capacity eviction and zero pressure")
        # Fixed64 payload encodes an80-byte DATA item. An initial 1GiB ring
        # therefore wraps once with64B PAD before its first eviction/pilot start.
        prefill = (1 << 30) // 80 + 1
        audit.check(start == prefill + 1 and details["start_head_pos"] == (1 << 30) + 80 and
                    details["start_tail_pos"] == 80 and details["start_tail_seq"] == 2,
                    f"{label} invocation {ordinal}: hand-computed fixed64 prefill state")


def audit_session(session_path: Path) -> dict[str, object]:
    audit = Audit()
    session = json.loads(session_path.read_text())
    base = ROOT / session["output_directory"]
    audit.check(session.get("status") == "passed", "orchestrator terminal status passed")
    provenance = session["provenance"]
    audit.check(len(provenance["git"]["sha"]) == 40 and
                isinstance(provenance["git"]["dirty"], bool), "actual Git revision and dirty flag")
    for entry in provenance["source_files"] + provenance["binaries"] + provenance["inputs"]:
        audit.identity(entry)
    audit.check(session.get("source_binary_changes") == [], "no source/binary changes during timing")
    environment = json.loads((base / "environment.json").read_text())
    audit.check(environment["controls"]["ac_online"] is True and
                environment["affinity"]["pin_verified"] and
                environment["affinity"]["cpu_is_core_pmu_member"], "fresh AC/P-core/child pin evidence")
    blocks = session["blocks"]
    audit.check([block["label"] for block in blocks] == ["M1", "M2-B256", "M2-B1024"],
                "three required serial blocks")
    total_rows, total_invocations = 0, 0
    for block in blocks:
        label = block["label"]
        directory = base / label
        command = json.loads((directory / "command.json").read_text())
        for key in ("stdout.log", "stderr.log", "gbench.json", "invocations.jsonl", "inputs.jsonl"):
            if key in command:
                audit.identity(command[key])
        audit.check(command["returncode"] == 0 and command["status"] == "ok" and
                    command["settling"]["elapsed_seconds"] >= 60,
                    f"{label}: exit status and monotonic settling")
        for flag in ("--benchmark_repetitions=15", "--benchmark_enable_random_interleaving=true",
                     "--benchmark_min_warmup_time=0.2", "--benchmark_min_time=0.5s"):
            audit.check(flag in command["argv"], f"{label}: {flag}")
        observations = [command["before"], *command["runtime_observations"], command["after"]]
        audit.check(all(item["power"]["ac_online"] is True for item in observations),
                    f"{label}: AC observed throughout block")
        raw = json.loads((directory / "gbench.json").read_text())
        rows = [row for row in raw["benchmarks"] if row["run_type"] == "iteration"]
        invocations = load_lines(directory / "invocations.jsonl")
        total_rows += len(rows)
        total_invocations += len(invocations)
        profiles = defaultdict(list)
        for row in rows:
            profiles[row["run_name"]].append(row)
            denominator = row.get("outputs_per_iteration", row.get("publishes_per_iteration"))
            audit.check(not row.get("error_occurred") and not row.get("skipped") and
                        row.get("time_unit") == "ns" and denominator and denominator > 0 and
                        math.isfinite(row["cpu_time"]) and row["cpu_time"] > 0 and
                        math.isfinite(row["real_time"]) and row["real_time"] > 0,
                        f"{label} {row['run_name']}/{row['repetition_index']}: valid individual outcome")
        expected_cases = 15 if label == "M1" else 2
        audit.check(len(profiles) == expected_cases, f"{label}: selected case count")
        for name, group in profiles.items():
            audit.check(sorted(row["repetition_index"] for row in group) == list(range(15)),
                        f"{label} {name}: 15 unique repetitions")
            needed = Counter(row["iterations"] for row in group)
            seen = Counter(row["iterations"] for row in invocations if row["profile"] == name)
            audit.check(all(seen[count] >= number for count, number in needed.items()),
                        f"{label} {name}: invocation coverage for measured iteration counts")
        audit.check([row["invocation"] for row in invocations] == list(range(len(invocations))),
                    f"{label}: complete ordered invocation log")
        audit.check(bool(invocations) and all(row["cpu_start"] == 2 and row["cpu_end"] == 2 and
                    row["seed"] == SEED and row["iterations"] > 0 and not row["failed"]
                    for row in invocations), f"{label}: all invocation CPU/seed/outcome boundaries")
        if label == "M1":
            audit_m1(audit, directory, rows, invocations)
        else:
            audit_m2(audit, label, raw["context"], invocations)
    audit.check(total_rows == 285, "285 required individual repetitions", observed=total_rows)
    return {"status": "passed" if not audit.errors else "failed", "checks": audit.checks,
            "errors": audit.errors, "session": relative(session_path),
            "session_sha256": sha(session_path), "individual_repetitions": total_rows,
            "audited_invocations": total_invocations,
            "limits": ["Invocation logs include calibration/warm-up; pinned GBench bulk JSON does not identify their exact mapping to measured rows. Every invocation is checked, and iteration-count coverage is required.",
                       "M1 expected input/output identities reuse saved independently sorted functional verification; this audit does not regenerate all full-sized lists.",
                       "M2 checks each adaptive prefix's sequence count and independent digest; different lengths are not required to have equal digests.",
                       "AC/frequency/CPU endpoints and a saved quiescence declaration do not prove exclusive host access or constant frequency."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", nargs="?", type=Path, default=ROOT / "results/p5/pilot-latest.json")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.output or ROOT / ("results/p5/pilot-digest-self-test.json" if args.self_test
                                       else "results/p5/pilot-audit.json")
    try:
        result = self_test() if args.self_test else audit_session(args.session.resolve())
    except Exception as exc:
        result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    result.update(at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), argv=sys.argv,
                  checker_sha256=sha(Path(__file__).resolve()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "result": relative(destination),
                      "checks": len(result.get("checks", [])), "cases": result.get("cases"),
                      "error": result.get("error")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
