"""Run with .venv/bin/python -m tiplog_py.itch (set PYTHONPATH=py)."""

import argparse
import gzip
import json
from pathlib import Path
import sys
import time

from .characterize import Statistics, write_tables, table_paths
from .protocol import BinaryFileReader
from .routing import Router
from tiplog_py.trace import TraceWriter, sha256_file
from tiplog_py._outputs import OutputTransaction


def time_ns(value):
    if value.isdecimal():
        number = int(value)
    else:
        try:
            hours, minutes, seconds = value.split(":")
            whole_seconds, dot, fraction = seconds.partition(".")
            if len(fraction) > 9 or (fraction and not fraction.isdecimal()):
                raise ValueError
            hour, minute, second = int(hours), int(minutes), int(whole_seconds)
            if not 0 <= hour <= 24 or not 0 <= minute < 60 or not 0 <= second < 60:
                raise ValueError
            if hour == 24 and (minute or second or int(fraction or "0")):
                raise ValueError
            number = (hour * 3600 + minute * 60 + second) * 1_000_000_000 + int(fraction.ljust(9, "0") or "0")
        except ValueError as exc:
            raise argparse.ArgumentTypeError("expected HH:MM:SS[.nanoseconds] or integer nanoseconds") from exc
    if not 0 <= number <= 86_400_000_000_000:
        raise argparse.ArgumentTypeError("timestamp outside the day")
    return number


def open_input(path):
    return gzip.open(path, "rb") if Path(path).suffix == ".gz" else open(path, "rb")


def _write_json(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n")


def measurement_result(args, full, window, reader, router, elapsed, boundary, *, destinations=None):
    result = full.summary() | {
        "schema_version": 1, "input": str(args.input),
        "total_uncompressed_bytes": reader.total_uncompressed_bytes,
        "terminated": reader.terminated, "incomplete": reader.incomplete,
        "limited": reader.limited, "limit_bytes": args.limit_bytes,
        "elapsed_seconds": elapsed,
        "uncompressed_bytes_per_second": reader.total_uncompressed_bytes / elapsed,
        "measurement_boundary": boundary,
        "routing": router.summary(),
        "window": {"start_inclusive_ns": args.start, "end_exclusive_ns": args.end,
                   **window.summary()},
    }
    if args.volumes_dir:
        result["l1"] = {
            "full_day": write_tables(full, args.volumes_dir, args.prefix + "_full_day", destinations=destinations),
            "window": write_tables(window, args.volumes_dir, args.prefix + "_window", destinations=destinations),
        }
    return result


def _table_outputs(args, *, full_day):
    if not args.volumes_dir:
        return []
    prefixes = ([args.prefix + "_full_day"] if full_day else []) + [args.prefix + "_window"]
    return [path for prefix in prefixes for path in table_paths(args.volumes_dir, prefix)]


def measure(args):
    targets = [args.output] + _table_outputs(args, full_day=True)
    with OutputTransaction(args.input, targets) as outputs:
        result = _measure(args, outputs)
        outputs.commit()
    print(json.dumps({key: result[key] for key in ("message_count", "total_uncompressed_bytes", "terminated", "incomplete", "limited", "elapsed_seconds", "uncompressed_bytes_per_second")}))
    return 0


def _measure(args, outputs):
    begin = time.perf_counter()
    full = Statistics()
    window = Statistics()
    router = Router()
    with open_input(args.input) as stream:
        reader = BinaryFileReader(stream, limit_bytes=args.limit_bytes)
        for payload in reader:
            topic = router.route(payload, validated=True)
            timestamp = int.from_bytes(payload[5:11], "big")
            full.add(payload, topic, timestamp)
            if args.start <= timestamp < args.end:
                window.add(payload, topic, timestamp)
    elapsed = time.perf_counter() - begin
    result = measurement_result(args, full, window, reader, router, elapsed,
                                "decompression, framing, validation, routing and full L1 aggregate updates; excludes JSON/CSV output",
                                destinations=outputs.staged)
    _write_json(outputs.path(args.output), result)
    return result


def convert(args):
    if args.also_flat and args.hierarchy != "H-spec":
        raise ValueError("--also-flat requires primary H-spec hierarchy")
    if (args.counts_output or args.volumes_dir) and args.hierarchy != "H-spec":
        raise ValueError("L1 tables/counts use primary H-spec hierarchy")
    traces = [args.output] + ([args.also_flat] if args.also_flat else [])
    targets = traces + [Path(str(target) + ".meta.json") for target in traces]
    if args.counts_output:
        targets.append(args.counts_output)
    targets += _table_outputs(args, full_day=bool(args.counts_output))
    with OutputTransaction(args.input, targets) as outputs:
        result = _convert(args, traces, outputs)
        outputs.commit()
    print(json.dumps(result))
    return 0


def _convert(args, traces, outputs):
    source_hash = sha256_file(args.input)
    if args.source_sha256 is not None and args.source_sha256.lower() != source_hash:
        raise ValueError("source SHA-256 does not match actual input file")
    writers = []
    router = Router(args.hierarchy)
    hierarchies = [args.hierarchy]
    if args.also_flat:
        hierarchies.append("H-flat")
    count_by_type = {}
    window_stats = Statistics()
    full_stats = Statistics() if args.counts_output else None
    begin = time.perf_counter()
    previous_ts = None
    inversions = 0
    try:
        for trace in traces:
            writers.append(TraceWriter(outputs.path(trace), source_hash))
        with open_input(args.input) as stream:
            reader = BinaryFileReader(stream, limit_bytes=args.limit_bytes)
            for payload in reader:
                timestamp = int.from_bytes(payload[5:11], "big")
                if previous_ts is not None and timestamp < previous_ts:
                    inversions += 1
                previous_ts = timestamp
                topic = router.route(payload, validated=True)
                if full_stats is not None:
                    full_stats.add(payload, topic, timestamp)
                if args.start <= timestamp < args.end:
                    topics = [topic]
                    if args.also_flat:
                        topics.append(topic if topic.startswith("itch/_unmapped/") else
                                      "/".join(topic.split("/", 2)[:2]) + "/" + chr(payload[0]))
                    for writer, topic in zip(writers, topics):
                        writer.append(topic, payload, timestamp)
                    kind = chr(payload[0])
                    count_by_type[kind] = count_by_type.get(kind, 0) + 1
                    window_stats.add(payload, topics[0], timestamp)
        for writer in writers:
            writer.finish()
    except BaseException:
        for writer in writers:
            writer.abort()
        raise
    elapsed = time.perf_counter() - begin
    metadata_outputs = []
    for writer, hierarchy, final in zip(writers, hierarchies, traces):
        metadata = {
            "schema_version": 1, "trace_format_version": 1,
            "source": {"path": str(args.input), "url": args.source_url,
                       "compressed_bytes": Path(args.input).stat().st_size,
                       "sha256": source_hash, "uncompressed_bytes_scanned": reader.total_uncompressed_bytes,
                       "messages_scanned": reader.message_count, "terminated": reader.terminated,
                       "incomplete": reader.incomplete, "limited": reader.limited},
            "trace": {"path": str(final), "bytes": writer.path.stat().st_size,
                      "sha256": sha256_file(writer.path), "records": writer.count,
                      "topics": len(writer.topics)},
            "window": {"start_inclusive_ns": args.start, "end_exclusive_ns": args.end},
            "hierarchy": hierarchy, "routing": router.summary(),
            "counts_by_type": count_by_type,
            "timestamp_inversions_full_scanned_stream": inversions,
            "source_order_preserved": True,
            "elapsed_seconds": elapsed,
            "uncompressed_bytes_per_second": reader.total_uncompressed_bytes / elapsed,
            "measurement_boundary": (
                "decompression, validation, routing, full L1 aggregates and selected record encoding; excludes final trace hash and metadata"
                if full_stats is not None else
                "decompression, validation, routing, window aggregates and selected record encoding; excludes final trace hash and metadata"),
            "attribution": "Original converter; protocol field interpretation from Nasdaq TotalView-ITCH 5.0 and BinaryFILE 1.0, S05/S06. No Nasdaq payload redistribution.",
        }
        _write_json(outputs.path(str(final) + ".meta.json"), metadata)
        metadata_outputs.append(metadata)
    if full_stats is not None:
        result = measurement_result(args, full_stats, window_stats, reader, router, elapsed,
                                    "combined full characterization and conversion: decompression, validation, routing, L1 aggregates and selected record encoding; excludes hashes/JSON/CSV output",
                                    destinations=outputs.staged)
        result["source_sha256"] = source_hash
        _write_json(outputs.path(args.counts_output), result)
    elif args.volumes_dir:
        write_tables(window_stats, args.volumes_dir, args.prefix + "_window", destinations=outputs.staged)
    return {"outputs": [metadata["trace"] for metadata in metadata_outputs], "elapsed_seconds": elapsed,
            "uncompressed_bytes_per_second": reader.total_uncompressed_bytes / elapsed,
            "limited": reader.limited, "terminated": reader.terminated}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("measure", "convert"):
        child = subparsers.add_parser(command)
        child.add_argument("input", type=Path)
        child.add_argument("--output", required=True, type=Path)
        child.add_argument("--start", type=time_ns, default=time_ns("09:30:00"))
        child.add_argument("--end", type=time_ns, default=time_ns("09:31:00"))
        child.add_argument("--limit-bytes", type=int, help="explicit partial-stream throughput pilot only")
        child.add_argument("--volumes-dir", type=Path)
        child.add_argument("--prefix", default="itch_20191230")
    converter = subparsers.choices["convert"]
    converter.add_argument("--source-sha256")
    converter.add_argument("--source-url", default="https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/12302019.NASDAQ_ITCH50.gz")
    converter.add_argument("--hierarchy", choices=("H-spec", "H-flat"), default="H-spec")
    converter.add_argument("--also-flat", type=Path)
    converter.add_argument("--counts-output", type=Path,
                           help="also accumulate complete-stream L1/CC-6 counts, avoiding a separate measurement pass")
    args = parser.parse_args(argv)
    if args.start >= args.end:
        parser.error("start must be before end")
    if args.limit_bytes is not None and args.limit_bytes < 1:
        parser.error("limit must be positive")
    return measure(args) if args.command == "measure" else convert(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, EOFError) as exc:
        print(f"ITCH error: {exc}", file=sys.stderr)
        sys.exit(2)
