"""Reproduce accepted-attempt selection in the P7 quiescence checker.

Creates synthetic control records in a temporary tree, never timing a workload.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("quiescence", ROOT / "scripts/check_p7_runtime_quiescence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")

with tempfile.TemporaryDirectory(prefix="tiplog-quiescence-probe-") as temporary:
    tree = Path(temporary)
    campaign = {"status": "passed", "rounds": []}
    for number in range(11):
        directory = tree / "raw" / f"round{number}"
        directory.mkdir(parents=True)
        # Old attempt is quiet, but the accepted attempt has 10 seconds of
        # competing CPU use. Both files are retained as the runner promises.
        old = directory / f"round-{number:02}-attempt-a.process-audit.jsonl"
        accepted = directory / f"round-{number:02}-attempt-b.process-audit.jsonl"
        old.touch()
        accepted.touch()
        # Directory iteration order is filesystem-dependent. Construct the
        # legitimate retry history whose accepted attempt sorts second in that
        # order; selection must be by the record, never by directory order.
        old, accepted = list(directory.glob(f"round-{number:02}-*.process-audit.jsonl"))
        def samples(ticks):
            process = {"pid": 77, "ppid": 1, "comm": "foreign-worker", "cpu": 2,
                       "user_ticks": ticks, "system_ticks": 0}
            return {"processes": [process]}
        old.write_text(json.dumps(samples(0)) + "\n" + json.dumps(samples(0)) + "\n")
        accepted.write_text(json.dumps(samples(0)) + "\n" + json.dumps(samples(1000)) + "\n")
        campaign["rounds"].append({
            "round": number, "kind": "warmup" if number == 0 else "measured",
            "output": str(accepted).replace(".process-audit.jsonl", ".jsonl"),
            "process_audit": str(accepted), "launcher_pid": 999,
            "cpu3_idle_ratio": 1.0,
            "settle": {"started_utc": "2026-10-26T00:00:00+00:00",
                       "finished_utc": "2026-10-26T00:01:00+00:00"}})
    save(tree / "campaign.json", campaign)
    sampler = tree / "samples.jsonl"
    sampler.write_text(json.dumps({"epoch": 1792972800, "cpu2": {"idle": 0, "total": 0}}) + "\n" +
                       json.dumps({"epoch": 1792972860, "cpu2": {"idle": 100, "total": 100}}) + "\n")
    save(tree / "results/p7/runtime-quiescence-rule.json", {
        "campaign": str(tree / "campaign.json"), "sampler_output": str(sampler),
        "clock_ticks_per_second": 100,
        "thresholds": {"cpu2_settle_idle_min": .95,
                       "foreign_cpu23_seconds_max": 1,
                       "cpu3_idle_ratio_min": .95}})
    previous = Path.cwd()
    try:
        os.chdir(tree)
        with contextlib.redirect_stdout(io.StringIO()):
            code = module.main()
        result = json.loads((tree / "results/p7/runtime-quiescence.json").read_text())
    finally:
        os.chdir(previous)
    selected = result["rounds"][0]["process_audit"]
    actual = module.foreign_cpu23_seconds(Path(campaign["rounds"][0]["process_audit"]), 999, 100)[0]
    observation = {"checker_status": result["status"], "checker_exit_code": code,
                   "selected_file": Path(selected).name,
                   "accepted_file": Path(campaign["rounds"][0]["process_audit"]).name,
                   "reported_foreign_cpu_seconds": result["rounds"][0]["foreign_cpu23_seconds"],
                   "accepted_attempt_foreign_cpu_seconds": actual}
    print(json.dumps(observation, indent=2))
    assert result["status"] == "passed" and code == 0
    assert selected != campaign["rounds"][0]["process_audit"] and actual == 10
