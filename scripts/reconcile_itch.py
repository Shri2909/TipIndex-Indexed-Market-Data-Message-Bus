#!/usr/bin/env python3
"""CC-6: reconcile independently produced full-stream counters exactly."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--cpp", type=Path, required=True)
    parser.add_argument("--bytes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    python = json.loads(args.python.read_text())
    cpp = json.loads(args.cpp.read_text())
    exact_bytes = int(args.bytes.read_text().strip())
    mismatches = []
    for key in ("total_uncompressed_bytes", "message_count", "payload_bytes", "terminated", "incomplete", "timestamp_inversions"):
        if python[key] != cpp[key]:
            mismatches.append({"field": key, "python": python[key], "cpp": cpp[key]})
    for table in ("by_type", "by_locate"):
        if set(python[table]) != set(cpp[table]):
            mismatches.append({"field": table, "error": "different key sets"})
        for key in set(python[table]) & set(cpp[table]):
            for field in ("count", "payload_bytes", "framed_bytes"):
                if python[table][key][field] != cpp[table][key][field]:
                    mismatches.append({"field": f"{table}.{key}.{field}", "python": python[table][key][field], "cpp": cpp[table][key][field]})
    if python["total_uncompressed_bytes"] != exact_bytes:
        mismatches.append({"field": "gzip_wc_bytes", "counter": python["total_uncompressed_bytes"], "independent": exact_bytes})
    if python.get("limited"):
        mismatches.append({"field": "limited", "error": "partial pilot cannot reconcile a full day"})
    summary = {"criterion": "CC-6/V04", "status": "passed" if not mismatches else "failed", "mismatches": mismatches,
               "compared_type_keys": len(python["by_type"]), "compared_locate_keys": len(python["by_locate"]),
               "message_count": python["message_count"], "uncompressed_bytes": exact_bytes,
               "inputs": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.python, args.cpp, args.bytes)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return int(bool(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
