"""Run and retain Phase 0 plumbing checks, stopping on the first failure."""

import datetime as dt
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parent.parent
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = Path(os.environ.get("CHECK_LOG_DIR", root / "results/p0" / run_id))
    destination.mkdir(parents=True, exist_ok=False)
    jobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL", "4")
    steps = []
    for preset in ("debug", "release", "asan-ubsan", "fuzz"):
        steps.extend([
            (f"{preset}-configure", ["cmake", "--preset", preset]),
            (f"{preset}-build", ["cmake", "--build", "--preset", preset, "--parallel", jobs]),
            (f"{preset}-ctest", ["ctest", "--preset", preset, "--output-on-failure", "--no-tests=error"]),
        ])
    steps.extend([
        ("python-dependencies", [sys.executable, "-m", "pip", "check"]),
        ("python-pytest", [sys.executable, "-m", "pytest", "-c", "py/pytest.ini", "py/tests", "-v"]),
    ])
    records = []
    for name, argv in steps:
        print(f"Running {shlex.join(argv)}", flush=True)
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        before = time.monotonic()
        with (destination / f"{name}.log").open("w") as output:
            try:
                result = subprocess.run(argv, cwd=root, stdout=output, stderr=subprocess.STDOUT, check=False)
                returncode = result.returncode
            except OSError as error:
                output.write(f"{error}\n")
                returncode = 127
        record = {"step": name, "argv": argv, "cwd": str(root), "started_utc": started,
                  "duration_seconds": time.monotonic() - before, "exit_code": returncode,
                  "log": f"{name}.log"}
        records.append(record)
        with (destination / "commands.jsonl").open("a") as output:
            output.write(json.dumps(record) + "\n")
        (destination / "summary.json").write_text(json.dumps({
            "status": "failed" if returncode else "running", "commands": records,
            "environment": {key: os.environ.get(key) for key in
                            ("MPLCONFIGDIR", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "ASAN_OPTIONS", "UBSAN_OPTIONS")},
        }, indent=2) + "\n")
        if returncode:
            print((destination / f"{name}.log").read_text()[-8000:], file=sys.stderr)
            print(f"FAILED; evidence: {destination}", file=sys.stderr)
            return returncode if returncode > 0 else 1
        print(f"Passed {name}", flush=True)
    summary = json.loads((destination / "summary.json").read_text())
    summary["status"] = "passed"
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"All Phase 0 plumbing checks passed; evidence: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
