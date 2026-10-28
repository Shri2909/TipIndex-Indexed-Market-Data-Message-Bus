"""Apply each audit mutant to an isolated copy, rebuild, run the project unit
tests and the audit tests, record killed/survived, and always restore."""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutants import MUTANTS  # noqa: E402

SRC, BUILD, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
PROJECT = ["tiplog_ring_test", "tiplog_index_test", "tiplog_engine_test", "tiplog_engine_index_test",
           "tiplog_engine_merge_test", "tiplog_merge_test", "tiplog_topics_subs_test", "tiplog_trace_test",
           "tiplog_driver_test", "tiplog_layout_test", "tiplog_oracle_test", "tiplog_oracle_tail_test",
           "tiplog_bench_contract_test"]
AUDIT = ["audit_engine_test", "audit_pressure_test", "audit_layout_test", "audit_trace_test", "audit_checker_test"]


def build():
    a = subprocess.run(["make", "-C", str(BUILD), "-j6", *AUDIT], capture_output=True, text=True)
    b = subprocess.run(["make", "-C", str(BUILD / "tiplog"), "-j6", *PROJECT], capture_output=True, text=True)
    return a.returncode == 0 and b.returncode == 0, (a.stderr + b.stderr)[-3000:]


def run(binary):
    try:
        return subprocess.run([str(binary), "--gtest_brief=1"], cwd=BUILD, capture_output=True,
                              text=True, timeout=900).returncode
    except subprocess.TimeoutExpired:
        return "timeout"


ok, log = build()
assert ok, log
for name in PROJECT:
    assert run(BUILD / "tiplog" / name) == 0, name
for name in AUDIT:
    assert run(BUILD / name) == 0, name
results = []
for mid, rel, old, new, desc in MUTANTS:
    path = SRC / rel
    text = path.read_text()
    assert text.count(old) == 1, (mid, text.count(old))
    path.write_text(text.replace(old, new))
    started = time.time()
    try:
        ok, log = build()
        if not ok:
            results.append({"id": mid, "desc": desc, "outcome": "compile_error", "log": log})
        else:
            project = [n for n in PROJECT if run(BUILD / "tiplog" / n) != 0]
            audit = [n for n in AUDIT if run(BUILD / n) != 0]
            results.append({"id": mid, "file": rel, "desc": desc, "killed_by_project": project,
                            "killed_by_audit": audit,
                            "outcome": "killed" if project else ("survived_project_killed_audit" if audit else "survived"),
                            "seconds": round(time.time() - started, 1)})
    finally:
        path.write_text(text)
    print(json.dumps(results[-1]), flush=True)
ok, _ = build()
assert ok
OUT.write_text(json.dumps(results, indent=1) + "\n")
