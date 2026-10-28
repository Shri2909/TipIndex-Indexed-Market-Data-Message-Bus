#!/usr/bin/env python3
"""Sample /proc/stat CPU2/CPU3 counters during the controlled P7 runtime campaign (read-only)."""
import argparse
import json
from pathlib import Path
import time


def counters():
    result = {}
    for line in Path("/proc/stat").read_text().splitlines():
        name, *values = line.split()
        if name in ("cpu2", "cpu3"):
            ticks = [int(value) for value in values]
            # idle + iowait; guest/guest_nice are already included in user/nice.
            result[name] = {"idle": ticks[3] + ticks[4], "total": sum(ticks[:8])}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=Path("results/p7/runtime-campaign.json"))
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--max-seconds", type=float, default=2700)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with args.output.open("w") as stream:
        while time.monotonic() - started < args.max_seconds:
            stream.write(json.dumps({"epoch": time.time(), "monotonic": time.monotonic(), **counters()}) + "\n")
            stream.flush()
            try:
                if json.loads(args.summary.read_text()).get("status") in ("passed", "failed", "interrupted"):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
