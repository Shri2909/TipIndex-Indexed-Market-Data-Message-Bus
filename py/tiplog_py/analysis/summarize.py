"""Analyze append-only normalized rows without hiding failed configurations."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .stats import median_summary, paired_ratio, stable_seed
from tiplog_py._outputs import OutputTransaction

STATUSES = {"ok", "history_expired", "fell_behind", "invalid_config", "crash", "oracle_mismatch"}
DEFAULT_SEED = 20191230
ROOT = Path(__file__).resolve().parents[3]
TABLE_NAMES = ('tip-statistics.csv', 'tip-outcomes.csv', 'tip-paired-ratios.csv')


def frequency_sidecar(reference, *, source_path, evidence_root=None):
    path = Path(reference)
    if not path.is_absolute():
        candidates = ((Path(evidence_root) / path,) if evidence_root is not None
                      else (ROOT / path, source_path.parent / path))
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    return path


def hydrate_noise(row: dict, *, source_path: Path, cache: dict, evidence_root=None) -> None:
    """Read final frequency sidecars without rewriting append-only raw rows.

    Micro observations cannot map every GBench repetition to a unique adaptive
    invocation. A matched block/attempt is therefore flagged conservatively if
    any of its observed endpoints is flagged. Missing evidence remains unknown.
    """
    recorded = isinstance(row.get("noise_flagged"), bool)
    if recorded and (evidence_root is None or not row.get("frequency_flags_reference")):
        row.setdefault("noise_observation_status", "recorded-in-row")
        return
    if not recorded:
        row["noise_flagged"] = None
        row["noise_observation_status"] = "unknown"
    reference = row.get("frequency_flags_reference")
    if not reference:
        return
    path = frequency_sidecar(reference, source_path=source_path, evidence_root=evidence_root)
    if evidence_root is not None and not path.is_file():
        raise ValueError(f"missing frequency sidecar in declared evidence workspace: {path}")
    if recorded:
        row.setdefault("noise_observation_status", "recorded-in-row")
        return
    if path not in cache:
        if path.is_file():
            document = json.loads(path.read_text())
            micro, process = defaultdict(list), defaultdict(list)
            for sample in document.get("samples", []):
                micro[(sample.get("block"), sample.get("attempt"))].append(sample)
            for sample in document.get("annotations", []):
                identity = (sample.get("config_id"), sample.get("process_round_id"),
                            sample.get("rep"), sample.get("warmup", False))
                process[identity].append(sample)
            # Index once: the full matrix has many process observations.
            # Repeated linear scans of its sidecar would be quadratic.
            cache[path] = (micro, process)
        else:
            cache[path] = None
    lookups = cache[path]
    if lookups is None:
        row["noise_observation_status"] = "missing-sidecar"
        return
    micro, process = lookups
    if row.get("block") is not None and row.get("attempt") is not None:
        samples = micro.get((row["block"], row["attempt"]), [])
        flags = [sample.get("flagged_over_10_percent") for sample in samples]
        scope = "Any flagged endpoint in this block and attempt; repetition/invocation mapping is unexposed"
        status = "sidecar-block-attempt"
    elif row.get("config_id") is not None and row.get("process_round_id") is not None and row.get("rep") is not None:
        identity = (row["config_id"], row["process_round_id"], row["rep"], row.get("warmup", False))
        samples = process.get(identity, [])
        # One immutable process observation must have one final annotation.
        if len(samples) != 1:
            row["noise_observation_status"] = "missing-or-duplicate-process-annotation"
            return
        flags = [samples[0].get("frequency_noisy")]
        scope = "Exact configuration/process round/repetition/warm-up annotation; all constituent endpoints for T2 cohorts"
        status = "sidecar-process-observation"
    else:
        row["noise_observation_status"] = "unmatched-observation-identity"
        return
    if any(flag is True for flag in flags):
        row["noise_flagged"] = True
    elif flags and all(flag is False for flag in flags):
        row["noise_flagged"] = False
    else:
        row["noise_observation_status"] = "missing-or-incomplete-matched-samples"
        return
    row["noise_observation_status"] = status
    row["noise_flag_scope"] = scope


def read_rows(path: Path, *, evidence_root=None) -> list[dict]:
    rows, sidecars = [], {}
    with Path(path).open() as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("status") not in STATUSES:
                raise ValueError(f"{path}:{number}: invalid or missing outcome status")
            row = dict(row)
            row.setdefault("raw_path", str(path))
            row["raw_line"] = number
            hydrate_noise(row, source_path=Path(path), cache=sidecars, evidence_root=evidence_root)
            rows.append(row)
    return rows


def field(row: dict, name: str, default=None):
    """Look up a normalized field, retaining zero/false as actual values."""
    for container in (row, row.get("config", {}), row.get("work", {})):
        if name in container:
            return container[name]
    return default


def arm(row: dict) -> str:
    if row.get("arm"):
        explicit = str(row["arm"])
        return "scan" if explicit.lower().startswith("scan/") else explicit
    mode = str(field(row, "mode", "unspecified"))
    kernel = field(row, "kernel")
    return mode + ("/" + str(kernel) if kernel and mode.lower() != "scan" else "")


def cpu_ns(row: dict):
    if row.get("cpu_ns") is not None:
        return row["cpu_ns"]
    if row.get("cpu_user_ns") is not None and row.get("cpu_sys_ns") is not None:
        return row["cpu_user_ns"] + row["cpu_sys_ns"]
    return None


def report_status(row: dict) -> str:
    """Retain engine outcome separately when its measurement fails CC-4."""
    if row["status"] == "ok" and row.get("oracle_validated") is False:
        return "oracle_mismatch"
    if row["status"] == "ok" and row.get("measurement_command_ok") is False:
        return "invalid_config"
    return row["status"]


def usable(row: dict) -> bool:
    return report_status(row) == "ok"


def numeric_metrics(row: dict) -> dict:
    result = {}
    for name in ("wall_ns", "item_cpu_ns", "item_wall_ns", "seek_ns",
                 "scan_ns_per_entry", "cpu_per_market_second",
                 "adjusted_cpu_per_market_second"):
        value = field(row, name)
        if value is not None:
            result[name] = value
    value = cpu_ns(row)
    if value is not None:
        result["cpu_ns"] = value
    def flatten(container, prefix):
        for name, value in container.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[prefix + name] = value
            elif isinstance(value, dict):
                flatten(value, prefix + name + ".")
    flatten(row.get("work", {}), "work.")
    flatten(row.get("memory", {}), "memory.")
    flatten(row.get("gauges", {}), "gauges.")
    if row.get("exp") == "T2" and value is not None:
        market_seconds = field(row, "market_seconds")
        publisher_on = field(row, "publish_index_on_cpu_ns")
        publisher_off = field(row, "publish_index_off_cpu_ns")
        if market_seconds is not None and publisher_on is not None and publisher_off is not None:
            publisher_seconds = field(row, "publish_window_market_seconds")
            if publisher_seconds is None:
                raise ValueError("T2 actual publisher timing requires its market-window duration")
            adjusted = t2_amortized(value, publisher_on, publisher_off, market_seconds,
                                    publish_market_seconds=publisher_seconds)
            result.setdefault("cpu_per_market_second", adjusted["cpu_per_market_second"])
            result.setdefault("adjusted_cpu_per_market_second", (
                adjusted["cpu_per_market_second"] if arm(row).lower() == "scan"
                else adjusted["adjusted_cpu_per_market_second"]))
    for name, value in result.items():
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"non-finite/non-numeric metric {name}: {value!r}")
        if name in {"wall_ns", "cpu_ns", "item_cpu_ns", "item_wall_ns", "seek_ns", "scan_ns_per_entry"} and value < 0:
            raise ValueError(f"negative measured duration {name}: {value!r}")
    return result


def summarize_rows(rows: list[dict], *, seed=DEFAULT_SEED) -> dict:
    groups = defaultdict(list)
    for row in rows:
        if row.get("status") not in STATUSES:
            raise ValueError(f"unknown outcome {row.get('status')!r}")
        if not row.get("exp") or not row.get("config_id"):
            raise ValueError("normalized row requires exp and config_id")
        groups[(row["exp"], row["config_id"])].append(row)
    configurations = []
    for (experiment, config_id), observations in sorted(groups.items()):
        for identity in ("preset", "compiler", "flags", "trace_sha256", "binary_sha256"):
            identities = {json.dumps(row[identity], sort_keys=True) for row in observations if row.get(identity) is not None}
            if len(identities) > 1:
                raise ValueError(f"{experiment}/{config_id}: incompatible {identity} identities; stratify the inputs")
        measured = [row for row in observations if not row.get("warmup", False)]
        warmups = [row for row in observations if row.get("warmup", False)]
        statuses = Counter(report_status(row) for row in measured)
        successful = [row for row in measured if usable(row)]
        metrics = defaultdict(list)
        for row in successful:
            for name, value in numeric_metrics(row).items():
                metrics[name].append(value)
        summary = {"exp": experiment, "config_id": config_id,
                   "comparison_id": observations[0].get("comparison_id"),
                   "config": observations[0].get("config", {}), "arm": arm(observations[0]),
                   "n_measured": len(measured), "n_ok": len(successful),
                   "n_non_ok": len(measured) - len(successful),
                   "n_validation_failed": sum(row.get("oracle_validated") is False or row["status"] == "oracle_mismatch" for row in measured),
                   "status_counts": {status: statuses[status] for status in sorted(STATUSES)},
                   "raw_status_counts": dict(sorted(Counter(row["status"] for row in measured).items())),
                   "warmup_count": len(warmups),
                   "warmup_status_counts": dict(sorted(Counter(report_status(row) for row in warmups).items())),
                   "noise_flagged_count": sum(row.get("noise_flagged") is True for row in measured),
                   "noise_observed_count": sum(isinstance(row.get("noise_flagged"), bool) for row in measured),
                   "noise_unknown_count": sum(not isinstance(row.get("noise_flagged"), bool) for row in measured),
                   "raw_evidence": sorted({str(row.get("raw_path", "")) for row in observations}),
                   "metric_scope": "successful full-outcome observations only; all statuses retained separately",
                   "metrics": {}}
        for name, values in sorted(metrics.items()):
            summary["metrics"][name] = median_summary(values, seed=stable_seed(seed, f"{experiment}/{config_id}/{name}"))
            summary["metrics"][name]["missing_among_ok"] = len(successful) - len(values)
        configurations.append(summary)
    return {"schema_version": 1, "seed": seed, "bootstrap_resamples": 10_000,
            "method": "seeded percentile-bootstrap median; paired ratios resample whole paired rounds",
            "all_status_counts": dict(sorted(Counter(report_status(row) for row in rows if not row.get("warmup", False)).items())),
            "raw_status_counts": dict(sorted(Counter(row["status"] for row in rows if not row.get("warmup", False)).items())),
            "validation_failed_count": sum(row.get("oracle_validated") is False or row["status"] == "oracle_mismatch" for row in rows if not row.get("warmup", False)),
            "row_count": len(rows), "configurations": configurations}


def paired_comparisons(rows: list[dict], *, seed=DEFAULT_SEED, metric="cpu_ns") -> list[dict]:
    """Compare Scan to each other arm only when every pairing is complete/ok.

    A failure makes the ratio unavailable, while ordinary successful-arm timing
    summaries remain in summarize_rows. This prevents fast expiry errors from
    appearing as a speedup and prevents an implicit selection of convenient pairs.
    """
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if not row.get("warmup", False) and row.get("comparison_id") is not None:
            groups[(row["exp"], str(row["comparison_id"]))][arm(row)].append(row)
    output = []
    for (experiment, comparison_id), arms in sorted(groups.items()):
        scans = [name for name in arms if name.lower() == "scan"]
        if len(scans) != 1:
            continue
        baseline = scans[0]
        for alternative in sorted(set(arms) - {baseline}):
            selected = {baseline: arms[baseline], alternative: arms[alternative]}
            blocks = {name: defaultdict(list) for name in selected}
            outcomes = {}
            missing_metric = Counter()
            missing_round = Counter()
            for name, observations in selected.items():
                outcomes[name] = dict(sorted(Counter(report_status(row) for row in observations).items()))
                for row in observations:
                    round_id = row.get("paired_round_id", row.get("round_id"))
                    if round_id is None:
                        missing_round[name] += 1
                        continue
                    if not usable(row):
                        continue
                    value = numeric_metrics(row).get(metric)
                    if value is None or value <= 0:
                        missing_metric[name] += 1
                        continue
                    blocks[name][str(round_id)].append(value)
            ids = {name: set(values) for name, values in blocks.items()}
            all_ids = ids[baseline] | ids[alternative]
            incomplete = (missing_metric or missing_round or ids[baseline] != ids[alternative]
                          or not all_ids or any(not usable(row) for observations in selected.values() for row in observations)
                          or any(len(blocks[baseline][key]) != len(blocks[alternative][key]) for key in all_ids))
            result = {"exp": experiment, "comparison_id": comparison_id,
                      "numerator": baseline, "denominator": alternative, "metric": metric,
                      "status_counts": outcomes, "missing_metric": dict(missing_metric),
                      "missing_round_id": dict(missing_round),
                      "arm_round_counts": {name: len(values) for name, values in ids.items()},
                      "unpaired_rounds": sorted(ids[baseline] ^ ids[alternative]),
                      "raw_evidence": sorted({str(row.get("raw_path", "")) for observations in selected.values() for row in observations})}
            if incomplete:
                result.update(status="incomplete_pairs", ratio=None, ci95_low=None, ci95_high=None)
            else:
                result.update(status="ok", **paired_ratio(blocks[baseline], blocks[alternative],
                              seed=stable_seed(seed, f"{experiment}/{comparison_id}/{alternative}/{metric}")))
            output.append(result)
    return output


def t2_amortized(replay_cpu_ns: float, publish_on_cpu_ns: float,
                 publish_off_cpu_ns: float, market_seconds: float, *,
                 publish_market_seconds: float | None = None) -> dict:
    """Add actual writer CPU per market second once to the whole reader cohort.

    The signed observed delta is retained; negative/noisy deltas are not clamped.
    The publisher arms must use the same actual window and the reader backlog
    must belong to that trace. Their durations can differ: divide each measured
    CPU contribution by its own market duration before adding the rates.
    """
    values = (replay_cpu_ns, publish_on_cpu_ns, publish_off_cpu_ns, market_seconds)
    if not all(math.isfinite(value) for value in values) or any(value < 0 for value in values[:3]) or market_seconds <= 0:
        raise ValueError("T2 requires nonnegative finite CPU times and positive market duration")
    publisher_seconds = market_seconds if publish_market_seconds is None else publish_market_seconds
    if not math.isfinite(publisher_seconds) or publisher_seconds <= 0:
        raise ValueError("T2 requires a positive actual publisher-window duration")
    delta = publish_on_cpu_ns - publish_off_cpu_ns
    return {"replay_cpu_ns": replay_cpu_ns, "publish_index_on_cpu_ns": publish_on_cpu_ns,
            "publish_index_off_cpu_ns": publish_off_cpu_ns, "publish_index_delta_cpu_ns": delta,
            "publish_window_market_seconds": publisher_seconds,
            "amortized_index_cpu_ns": delta * market_seconds / publisher_seconds,
            "market_seconds": market_seconds,
            "cpu_per_market_second": replay_cpu_ns / 1e9 / market_seconds,
            "adjusted_cpu_per_market_second": (replay_cpu_ns / market_seconds + delta / publisher_seconds) / 1e9}


def build(path: Path, output: Path, *, seed=DEFAULT_SEED, evidence_root=None):
    path, output = Path(path), Path(output)
    rows = read_rows(path, evidence_root=evidence_root)
    sidecars = {frequency_sidecar(row['frequency_flags_reference'], source_path=path, evidence_root=evidence_root)
                for row in rows if row.get('frequency_flags_reference')}
    outputs = [output, *(output.parent / name for name in TABLE_NAMES)]
    transaction = OutputTransaction(path, outputs, additional_sources=sidecars)
    summary = summarize_rows(rows, seed=seed)
    summary["paired_comparisons"] = paired_comparisons(rows, seed=seed)
    summary["input"] = str(path)
    with Path(path).open("rb") as stream:
        summary["input_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    with transaction:
        transaction.path(output).write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
        write_tables(summary, output.parent, destinations=transaction.staged)
        transaction.commit()
    return summary


def write_tables(summary: dict, output: Path, *, destinations=None):
    """Save auditable complete tables; every row carries non-ok/raw references."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    def target(name):
        path = output / name
        return destinations[path] if destinations is not None else path
    with target("tip-statistics.csv").open("w", newline="") as stream:
        columns = ("exp", "config_id", "arm", "metric", "n", "median", "q1", "q3", "iqr",
                   "min", "max", "ci95_low", "ci95_high", "n_non_ok", "n_validation_failed", "status_counts",
                   "noise_flagged_count", "noise_observed_count", "noise_unknown_count", "raw_evidence", "bootstrap_seed", "bootstrap_resamples")
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in summary["configurations"]:
            for name, metric in item["metrics"].items():
                row = {key: item[key] for key in ("exp", "config_id", "arm", "n_non_ok", "n_validation_failed", "noise_flagged_count", "noise_observed_count", "noise_unknown_count")}
                row.update(metric, metric=name, status_counts=json.dumps(item["status_counts"], sort_keys=True),
                           raw_evidence=json.dumps(item["raw_evidence"]))
                writer.writerow(row)
    with target("tip-outcomes.csv").open("w", newline="") as stream:
        columns = ("exp", "config_id", "arm", "n_measured", "n_ok", "n_non_ok", "n_validation_failed", "warmup_count", "noise_flagged_count", "noise_observed_count", "noise_unknown_count", "status_counts", "raw_evidence")
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in summary["configurations"]:
            writer.writerow(dict(item, status_counts=json.dumps(item["status_counts"], sort_keys=True), raw_evidence=json.dumps(item["raw_evidence"])))
    with target("tip-paired-ratios.csv").open("w", newline="") as stream:
        columns = ("exp", "comparison_id", "numerator", "denominator", "metric", "status", "ratio",
                   "ci95_low", "ci95_high", "paired_rounds", "status_counts", "unpaired_rounds", "raw_evidence")
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in summary.get("paired_comparisons", []):
            writer.writerow(dict(item, status_counts=json.dumps(item["status_counts"], sort_keys=True),
                                 unpaired_rounds=json.dumps(item["unpaired_rounds"]), raw_evidence=json.dumps(item["raw_evidence"])))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/derived/tip-summary.json"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--evidence-root", type=Path,
                        help="Declared workspace for relative frequency sidecar references")
    args = parser.parse_args(argv)
    result = build(args.rows, args.output, seed=args.seed, evidence_root=args.evidence_root)
    print(json.dumps({"output": str(args.output), "configurations": len(result["configurations"]), "rows": result["row_count"]}))


if __name__ == "__main__":
    main()
