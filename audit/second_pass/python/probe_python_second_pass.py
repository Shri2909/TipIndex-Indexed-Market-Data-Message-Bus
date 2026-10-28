"""Read-only product probes; all temporary inputs and mutations stay in scratch."""
from __future__ import annotations
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from tiplog_py.exp.audit import acceptance
from tiplog_py.exp.oracle import TraceIndex
from tiplog_py.exp.run import aggregate_t2, publish_commit
from tiplog_py.exp.synthetic import schedule
from tiplog_py.itch.__main__ import convert, measure
from tiplog_py.trace.format import TraceReader, TraceWriter


def input_bytes():
    payload = b"S" + bytes(10) + b"O"
    return len(payload).to_bytes(2, "big") + payload + bytes(2)


def conversion_arguments(source, output, **overrides):
    return SimpleNamespace(input=source, output=output, also_flat=None,
        hierarchy="H-spec", counts_output=None, volumes_dir=None, prefix="probe",
        source_sha256=None, source_url="local synthetic audit fixture", start=0,
        end=1_000_000_000, limit_bytes=None, **overrides)


def probe(work):
    results = {}
    # The converter claims its target preflight preserves the input, but omits
    # the actual temporary filename which TraceWriter opens with w+b.
    source = work / "source.mdt.partial"
    source.write_bytes(input_bytes())
    original = source.read_bytes()
    args = conversion_arguments(source, work / "source.mdt")
    error = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            convert(args)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    results["convert_input_equals_temporary_output"] = {
        "before_bytes": len(original), "input_exists_after": source.exists(),
        "input_preserved": source.exists() and source.read_bytes() == original,
        "exception": error,
    }
    assert not results["convert_input_equals_temporary_output"]["input_preserved"]

    source = work / "measure-input.itch"
    source.write_bytes(input_bytes())
    original = source.read_bytes()
    args = conversion_arguments(source, source)
    with contextlib.redirect_stdout(io.StringIO()):
        measure(args)
    results["measure_output_equals_input"] = {
        "before_bytes": len(original), "after_bytes": source.stat().st_size,
        "input_preserved": source.read_bytes() == original,
        "replacement_schema_version": json.loads(source.read_text())["schema_version"],
    }
    assert not results["measure_output_equals_input"]["input_preserved"]

    # Alignment-inclusive DATA size needs 17 bits at valid u16 payload lengths.
    cases = []
    for length in (65512, 65513, 65535):
        path = work / f"payload-{length}.mdt"
        with TraceWriter(path, "01" * 32) as writer:
            writer.append("topic/partition/event", bytes(length), 0)
        with TraceReader(path) as reader:
            valid_count = len(list(reader))
        checker = Path(__file__).resolve().parents[3] / "build/release/tiplog_trace_check"
        checked = subprocess.run([str(checker), str(path)], capture_output=True, text=True)
        error = None
        index_size = None
        try:
            with TraceIndex(path, work / "index-cache") as index:
                index_size = int(index.rows[0]["size"])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        cases.append({"payload_bytes": length, "trace_reader_records": valid_count,
                      "cpp_trace_check_returncode": checked.returncode,
                      "oracle_record_size": index_size, "oracle_exception": error})
    results["valid_trace_payload_boundary"] = cases
    assert cases[0]["oracle_record_size"] == 65528
    assert all(case["oracle_exception"].startswith("OverflowError") for case in cases[1:])

    try:
        schedule(records=1, partitions=2, zipf=0, run_length=1,
                 seed=1, mix=[(65535, 1)])
    except Exception as exc:
        results["synthetic_max_payload"] = f"{type(exc).__name__}: {exc}"
    assert results["synthetic_max_payload"].startswith("OverflowError")

    # The durable marker retains the entire process payload; recovery could
    # reconstruct a torn final JSONL row, but reads it as ordinary JSON first.
    journal_dir = work / "torn-journal"
    journal_dir.mkdir()
    rows = [dict(process_round_id="r0", config_id=name, status="ok") for name in ("a", "b")]
    (journal_dir / "runs.jsonl").write_text(json.dumps(rows[0]) + '\n{"process_round_id": "r0", "config')
    payload = {"status": "pending", "collections": {"runs.jsonl": rows},
               "completion": {"id": "r0", "rep": 0, "workload_id": "fixture"}}
    marker = journal_dir / "process.commit.json"
    marker.write_text(json.dumps(payload))
    error = None
    try:
        publish_commit(journal_dir, marker, payload, {"status": "running", "completed_processes": []}, {})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    results["pending_journal_torn_final_line"] = {
        "exception": error, "marker_still_pending": json.loads(marker.read_text())["status"] == "pending",
    }
    assert error.startswith("JSONDecodeError")

    # Configurable T2 backlog is carried into each row but overwritten with 10
    # during aggregation, changing both CPU/market-second and writer amortization.
    reader = dict(exp="T2", config=dict(reader_count=1, reader_index=0,
        mode="indexed", kernel="binheap", cache_treatment="repeat-warm", C=1024,
        B=64, market_seconds=20, backlog_seconds=20), status="ok",
        oracle={"status": "passed"}, out_count=1, wall_ns=1, cpu_ns=20_000_000_000,
        cpu_user_ns=20_000_000_000, cpu_sys_ns=0)
    aggregated = aggregate_t2([reader])[0]
    results["t2_configurable_backlog"] = {"requested_seconds": 20,
        "aggregated_market_seconds": aggregated["config"]["market_seconds"],
        "reported_cpu_seconds_per_market_second": aggregated["cpu_ns"] / 1e9 / aggregated["config"]["market_seconds"],
        "correct_cpu_seconds_per_market_second": 1}
    assert aggregated["config"]["market_seconds"] == 10

    # This helper is deliberately distinguished from the campaign's stronger
    # check_p6_experiments.audit_session(), which separately validates the plan.
    observations = [dict(config_id="only-one-config", exp="T1", rep=rep,
        warmup=rep < 0, process_round_id=f"p{rep}", process_pid=100 + rep,
        oracle_validated=True, oracle={"status": "passed"}, cpu_start=2,
        cpu_end=2, status="ok") for rep in range(-1, 10)]
    results["acceptance_without_measured_commands"] = acceptance(observations)["status"]
    return results


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="tiplog-python-audit-", dir="/tmp") as scratch:
        result = probe(Path(scratch))
    print(json.dumps(result, indent=2, sort_keys=True))
