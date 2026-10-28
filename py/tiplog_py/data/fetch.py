"""Download the authorized Nasdaq sample, validate gzip, and save identity."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["nasdaq"], required=True)
    parser.add_argument("--file", choices=["12302019.NASDAQ_ITCH50.gz"], required=True)
    parser.add_argument("--dest", type=Path, default=Path("data/raw"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
    parser.add_argument("--connections", type=int, choices=range(1, 17), default=1)
    args = parser.parse_args(argv)
    url = "https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/" + args.file
    args.dest.mkdir(parents=True, exist_ok=True)
    path = args.dest / args.file
    lock = (args.dest / (args.file + ".lock")).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError("An acquisition already owns this destination") from exc
    evidence = Path("results/p1")
    evidence.mkdir(parents=True, exist_ok=True)
    commands = []
    invocation_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")

    def run(argv):
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        result = subprocess.run(argv, check=False)
        commands.append({"argv": list(map(str, argv)), "started_utc": started, "exit_code": result.returncode})
        (evidence / f"acquisition-{invocation_id}-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        result.check_returncode()

    headers = evidence / "nasdaq-head.txt"
    run(["curl", "--fail", "--location", "--silent", "--show-error", "--connect-timeout", "30", "--max-time", "120", "--head", "--output", str(headers), url])
    fields = {}
    for line in headers.read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.lower().strip()] = value.strip()
    size = int(fields["content-length"])
    if path.exists() and path.stat().st_size > size:
        raise ValueError("Existing file exceeds the source size; preserving it for inspection")
    old = json.loads(args.manifest.read_text()) if args.manifest.exists() else None
    if old is not None:
        if old.get("source_url") != url or old.get("last_modified") != fields.get("last-modified"):
            raise ValueError("Source identity changed; preserving existing file instead of resuming")
    identity = {"url": url, "size_bytes": size, "last_modified": fields.get("last-modified"), "etag": fields.get("etag")}
    state = args.dest / (args.file + ".acquisition.json")
    if state.exists() and json.loads(state.read_text()) != identity:
        raise ValueError("Source changed since partial acquisition; preserving partial data")
    state.write_text(json.dumps(identity, indent=2) + "\n")
    if not path.exists() or path.stat().st_size < size:
        if args.connections == 1:
            run(["curl", "--fail", "--location", "--show-error", "--retry", "5", "--retry-all-errors",
                 "--connect-timeout", "30", "--speed-limit", "1024", "--speed-time", "120", "--max-filesize", str(size),
                 "--continue-at", "-", "--dump-header", str(evidence / "nasdaq-download-headers.txt"),
                 "--output", str(path), url])
        else:
            parts = args.dest / (args.file + ".parts")
            parts.mkdir(exist_ok=True)
            chunk = 16 * 1024 * 1024
            jobs = [(start, min(size - 1, start + chunk - 1)) for start in range(0, size, chunk)]

            def fetch_part(bounds):
                start, end = bounds
                part = parts / f"{start:012d}-{end:012d}"
                header = part.with_suffix(".headers")
                expected = end - start + 1
                expected_range = f"content-range: bytes {start}-{end}/{size}"
                if part.exists() and part.stat().st_size == expected and header.exists() and expected_range in header.read_text().lower():
                    return part
                temporary = part.with_suffix(".partial")
                argv = ["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "5", "--retry-all-errors",
                        "--connect-timeout", "30", "--max-time", "1800", "--speed-limit", "1024", "--speed-time", "120", "--max-filesize", str(expected),
                        "--range", f"{start}-{end}", "--header", "If-Range: " + str(fields.get("etag") or fields.get("last-modified")),
                        "--dump-header", str(header), "--output", str(temporary), url]
                with part.with_suffix(".log").open("w") as log:
                    result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=False)
                part.with_suffix(".command.json").write_text(json.dumps({"argv": argv, "exit_code": result.returncode}, indent=2) + "\n")
                result.check_returncode()
                if temporary.stat().st_size != expected or expected_range not in header.read_text().lower():
                    raise ValueError(f"Unverified range response for {start}-{end}; preserving it")
                os.replace(temporary, part)
                return part

            with ThreadPoolExecutor(max_workers=args.connections) as executor:
                futures = [executor.submit(fetch_part, job) for job in jobs]
                for completed, future in enumerate(as_completed(futures), 1):
                    part = future.result()
                    print(f"Verified range {completed}/{len(jobs)}: {part.name}", flush=True)
            assembled = path.with_suffix(path.suffix + ".assembled")
            with assembled.open("wb") as output:
                for start, end in jobs:
                    with (parts / f"{start:012d}-{end:012d}").open("rb") as source:
                        shutil.copyfileobj(source, output, 1024 * 1024)
            if assembled.stat().st_size != size:
                raise ValueError("Assembled size mismatch")
            if path.exists():
                os.replace(path, path.with_suffix(path.suffix + ".previous-partial"))
            os.replace(assembled, path)
    if path.stat().st_size != size:
        raise ValueError("Downloaded size does not equal HEAD Content-Length")
    run(["gzip", "-t", str(path)])
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if old is not None and old.get("sha256") is not None and digest != old["sha256"]:
        raise ValueError("Downloaded SHA-256 differs from recorded source identity; preserving file and manifest for inspection")
    manifest = {"source": args.source, "source_url": url, "path": str(path), "size_bytes": size,
                "last_modified": fields.get("last-modified"), "etag": fields.get("etag"),
                "accept_ranges": fields.get("accept-ranges"), "sha256": digest,
                "downloaded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "gzip_validation": "passed",
                "redistribution": "Raw and message-level derived data stay local and ignored"}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
