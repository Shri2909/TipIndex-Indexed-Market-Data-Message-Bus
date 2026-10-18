#!/usr/bin/env python3
"""Execute a check and retain its exact arguments, context, output and status."""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase")
    parser.add_argument("label")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not argv:
        parser.error("a command is required")
    root = Path(__file__).resolve().parent.parent
    destination = root / "results" / args.phase
    destination.mkdir(parents=True, exist_ok=True)
    identifier = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log = destination / f"{args.label}-{identifier}.log"
    environment = dict(os.environ)
    environment.setdefault("ASAN_OPTIONS", "detect_leaks=1:abort_on_error=1")
    environment.setdefault("UBSAN_OPTIONS", "print_stacktrace=1:halt_on_error=1")
    environment.setdefault("MPLCONFIGDIR", str(root / "build/matplotlib"))
    environment.setdefault("PIP_CACHE_DIR", str(root / "build/pip-cache"))
    environment.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    environment.setdefault("PYTHONPATH", str(root / "py"))
    record = {"label": args.label, "argv": argv, "cwd": str(root), "started_utc": identifier,
              "environment": {k: environment.get(k) for k in
                              ("ASAN_OPTIONS", "UBSAN_OPTIONS", "MPLCONFIGDIR", "PYTHONPATH", "TIPLOG_EXECUTION_CONTEXT")},
              "log": str(log.relative_to(root)), "status": "running"}
    status = log.with_suffix(".json")
    status.write_text(json.dumps(record, indent=2) + "\n")
    print(f"Starting {args.label}; log: {log}", flush=True)
    before = time.monotonic()
    with log.open("w") as output:
        try:
            code = subprocess.run(argv, cwd=root, env=environment, stdout=output, stderr=subprocess.STDOUT).returncode
        except OSError as error:
            output.write(str(error) + "\n")
            code = 127
    record.update(exit_code=code, duration_seconds=time.monotonic() - before,
                  status="passed" if code == 0 else "failed")
    status.write_text(json.dumps(record, indent=2) + "\n")
    with (destination / "commands.jsonl").open("a") as output:
        output.write(json.dumps(record) + "\n")
    print(f"{args.label}: {record['status']} (exit {code}, {record['duration_seconds']:.3f}s)", flush=True)
    if code:
        print(log.read_text()[-5000:], flush=True)
    return code if code >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
