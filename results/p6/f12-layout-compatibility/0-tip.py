"""Generate P6 F06–F13 exclusively from actual saved normalized observations.

Missing experiments/metrics are errors. Complete machine-readable summaries
accompany the charts; no absent counter or allocator measurement becomes zero.
"""

import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tiplog_py.analysis.summarize import build as analyze, field


def _config(item, *names, default=None):
    for name in names:
        if item.get(name) is not None:
            return item[name]
        if item.get("config", {}).get(name) is not None:
            return item["config"][name]
    return default


def _metric(item, *names):
    for name in names:
        for candidate in (name, "work." + name, "memory." + name, "work.memory." + name, "gauges." + name, "work.gauges." + name):
            if candidate in item["metrics"]:
                return item["metrics"][candidate]
    return None


def _required_metric(item, *names):
    result = _metric(item, *names)
    if result is None:
        raise ValueError(f"{item['config_id']}: missing required metric {names}")
    return result


def _number(value):
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    raise ValueError(f"required numeric figure coordinate is missing/invalid: {value!r}")


def _axes(count, *, columns=3, width=4.7, height=3.5):
    columns = min(columns, max(1, count))
    figure, axes = plt.subplots(math.ceil(count / columns), columns,
                                figsize=(width * columns, height * math.ceil(count / columns)),
                                squeeze=False)
    flat = list(axes.flat)
    for axis in flat[count:]:
        axis.set_visible(False)
    return figure, flat


def _save(figure, output, name, *, status_note=""):
    if status_note:
        figure.text(.01, .006, status_note, fontsize=7)
    figure.tight_layout(rect=(0, .025, 1, 1))
    outputs = []
    for extension in ("png", "pdf"):
        path = output / f"{name}.{extension}"
        figure.savefig(path, dpi=160)
        outputs.append(str(path))
    plt.close(figure)
    return outputs


def _status_note(items):
    return (f"Measured outcomes: ok={sum(item['n_ok'] for item in items)}, "
            f"non-ok={sum(item['n_non_ok'] for item in items)}; failures retained in tip-summary.json. "
            "Error bars: seeded 10,000-resample 95% median bootstrap CIs.")


def _lines(axis, items, x, y, series, *, scale=1.0, errors=True):
    groups = defaultdict(list)
    for item in items:
        if item["n_ok"]:
            coordinate = _number(x(item))
            metric = y(item)
            if metric is not None:
                groups[str(series(item))].append((coordinate, metric, item["config_id"]))
    plotted = []
    for label, observations in sorted(groups.items()):
        observations.sort(key=lambda point: (point[0], point[2]))
        # Never silently merge distinct configurations at one x coordinate.
        if len({point[0] for point in observations}) != len(observations):
            raise ValueError(f"ambiguous figure series {label}: multiple configurations at one x; facet the remaining dimensions")
        xs = [point[0] for point in observations]
        ys = [point[1]["median"] * scale for point in observations]
        if errors:
            low = [max(0, (point[1]["median"] - point[1]["ci95_low"]) * scale) for point in observations]
            high = [max(0, (point[1]["ci95_high"] - point[1]["median"]) * scale) for point in observations]
            axis.errorbar(xs, ys, yerr=[low, high], marker="o", markersize=3, linewidth=.9, label=label)
        else:
            axis.plot(xs, ys, marker="o", markersize=3, linewidth=.9, label=label)
        plotted.extend(point[2] for point in observations)
    if groups:
        axis.legend(fontsize="xx-small")
    else:
        axis.text(.5, .5, "No successful observations; see status counts", ha="center", transform=axis.transAxes)
    axis.grid(alpha=.2)
    return plotted


def _facet(items, key):
    groups = defaultdict(list)
    for item in items:
        groups[str(key(item))].append(item)
    return sorted(groups.items())


def _kernel(item):
    return str(_config(item, "kernel", default=item["arm"]))


def _cache(item):
    return str(_config(item, "cache_treatment", "cache", default="unspecified"))


def _pattern(item):
    return str(_config(item, "pattern", "owner_pattern", "distribution", default="unspecified"))


def _touch(item):
    return "M1-touch" if item["exp"] == "M1-touch" or _config(item, "touch", default=False) else "M1"


def _run_length(item):
    value = _config(item, "L", "run_length", "mean_run_length")
    if value is not None:
        return value
    pattern = _pattern(item)
    if pattern.startswith("geometric"):
        return float(pattern.removeprefix("geometric").lstrip("_-"))
    return None


def _breadth(item):
    return _config(item, "breadth", "k", "partitions_subscribed", "N")


def _subscription(item):
    name = _config(item, "name", "subscription", "subscription_family", "subscription_kind", default="unspecified")
    return re.sub(r"\d+$", "", str(name))


def _tip_facet(item):
    return (f"{_cache(item)}; backlog={_config(item, 'backlog_seconds', 'backlog_s', 'backlog', default='unspecified')}s; "
            f"C={_config(item, 'ring_bytes', 'C', default='specified in raw')}")


def _arm_series(item):
    # Effective fallback is reported in the raw summary; requested arm is kept.
    return item["arm"] + "; " + _subscription(item)


def _memory(item, name):
    return _required_metric(item, name)["median"]


def build(rows_path: Path, output: Path, *, seed=20191230, summary_path=None):
    """Write all eight figures and an input/coverage manifest, or fail explicitly."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = Path(summary_path or output.parent / "derived/tip-summary.json")
    summary = analyze(Path(rows_path), summary_path, seed=seed)
    items = summary["configurations"]
    experiments = defaultdict(list)
    for item in items:
        experiments[item["exp"]].append(item)
    for experiment in ("M1", "M2", "M3", "T1", "T2", "T3", "T5"):
        if not experiments[experiment]:
            raise ValueError(f"F06–F13 require actual {experiment} observations")
    m1 = experiments["M1"] + experiments["M1-touch"]
    if not any(_touch(item) == "M1-touch" for item in m1):
        raise ValueError("M1-touch actual observations are required")
    artifacts, coverage = [], {}

    # F06: every k/pattern/touch arm, with other fixed dimensions faceted.
    facets = _facet(m1, lambda item: f"{_touch(item)}; {_pattern(item)}; N={_config(item, 'N', 'outputs', default='specified in raw')}")
    figure, axes = _axes(len(facets))
    used = []
    for axis, (label, selected) in zip(axes, facets):
        used += _lines(axis, selected, lambda item: _config(item, "k"),
                       lambda item: _required_metric(item, "item_cpu_ns"), _kernel)
        axis.set(xscale="log", xlabel="Requested input lists k", ylabel="CPU ns / output", title=label)
    artifacts += _save(figure, output, "F06_merge_cost_vs_k", status_note=_status_note(m1))
    coverage["F06"] = sorted(set(used))

    # Tier B F07 is run-length sensitivity; no galloping result is invented.
    runs = [item for item in m1 if _run_length(item) is not None]
    if not runs:
        raise ValueError("F07 requires actual geometric-run measurements")
    facets = _facet(runs, lambda item: f"{_touch(item)}; k={_config(item, 'k')}")
    figure, axes = _axes(len(facets))
    used = []
    for axis, (label, selected) in zip(axes, facets):
        used += _lines(axis, selected, _run_length, lambda item: _required_metric(item, "item_cpu_ns"), _kernel)
        axis.set(xscale="log", xlabel="Geometric mean owner-run length L", ylabel="CPU ns / output", title=label)
    artifacts += _save(figure, output, "F07_merge_run_length", status_note=_status_note(runs) + " Galloping: deferred Tier C.")
    coverage["F07"] = sorted(set(used))

    m2 = experiments["M2"]
    facets = _facet(m2, lambda item: f"B={_config(item, 'B', 'block_entries')}; {_pattern(item)}; payload={_config(item, 'payload', 'payload_size', 'payload_profile')}")
    figure, axes = _axes(len(facets))
    used = []
    for axis, (label, selected) in zip(axes, facets):
        used += _lines(axis, selected, lambda item: _config(item, "P", "partitions"),
                       lambda item: _required_metric(item, "item_cpu_ns"), lambda item: str(_config(item, "index_enabled", "index", default=item["arm"])))
        axis.set(xscale="log", xlabel="Partition count P", ylabel="CPU ns / publish", title=label)
    artifacts += _save(figure, output, "F08_publish_index_cost", status_note=_status_note(m2))
    coverage["F08"] = sorted(set(used))

    t1 = experiments["T1"]
    facets = _facet(t1, _tip_facet)
    figure, axes = _axes(len(facets), columns=2)
    used = []
    for axis, (label, selected) in zip(axes, facets):
        used += _lines(axis, selected, _breadth, lambda item: _required_metric(item, "cpu_ns"), _arm_series, scale=1e-6)
        axis.set(xscale="log", yscale="log", xlabel="Requested subscription breadth", ylabel="Recovery CPU ms", title=label)
    artifacts += _save(figure, output, "F09_catchup_breadth", status_note=_status_note(t1))
    coverage["F09"] = sorted(set(used))

    facets = [(f"{label}; {metric}", selected, metric) for label, selected in _facet(t1, _tip_facet)
              for metric in ("entries_visited", "records_fetched", "bytes_inspected")]
    figure, axes = _axes(len(facets))
    used = []
    for axis, (label, selected, metric) in zip(axes, facets):
        used += _lines(axis, selected, _breadth, lambda item: _required_metric(item, metric), _arm_series)
        axis.set(xscale="log", yscale="symlog", xlabel="Requested subscription breadth", ylabel=metric.replace("_", " "), title=label)
    artifacts += _save(figure, output, "F10_replay_work", status_note=_status_note(t1) + " Bytes are logical inspected bytes.")
    coverage["F10"] = sorted(set(used))

    # Runner-normalized T2 cohort rows must already sum R readers and link the
    # actual same-window publisher arms; no synthetic-M2 substitution is allowed.
    t2 = experiments["T2"]
    facets = _facet(t2, _cache)
    figure, axes = _axes(len(facets), columns=2)
    used = []
    for axis, (label, selected) in zip(axes, facets):
        for metric, suffix in (("cpu_per_market_second", "recovery only"),
                               ("adjusted_cpu_per_market_second", "+ actual writer delta")):
            eligible = [item for item in selected if _metric(item, metric) is not None]
            if not eligible and any(item["n_ok"] for item in selected):
                raise ValueError(f"F11 missing T2 {metric}; aggregate reader cohorts and maintenance first")
            used += _lines(axis, eligible, lambda item: _config(item, "R", "readers"),
                           lambda item: _required_metric(item, metric), lambda item: item["arm"] + "; " + suffix)
        axis.set(xscale="log", ylabel="CPU seconds / market second", xlabel="Sequential readers R", title=label)
    artifacts += _save(figure, output, "F11_many_readers_cpu", status_note=_status_note(t2) + " Publisher paused during recovery.")
    coverage["F11"] = sorted(set(used))

    # F12: one panel per generator/cache stratum; paired Scan/Indexed ratios.
    t3 = experiments["T3"]
    # Config summaries keep comparison identities below even when no ratio is
    # eligible; callers can inspect the explicit incomplete_pairs records.
    facets = _facet(t3, lambda item: f"P={_config(item, 'P', 'partitions')}; Zipf={_config(item, 'Z', 'zipf', 'zipf_s')}; L={_config(item, 'L', 'run_length')}; {_cache(item)}")
    figure, axes = _axes(len(facets))
    used = []
    finite_ratios = []
    panel_points = []
    for label, selected in facets:
        scan = {}
        for item in selected:
            if item["arm"].lower() == "scan":
                scan[(_config(item, "k", "breadth"), _config(item, "selectivity"))] = item
        points = []
        for item in selected:
            key = (_config(item, "k", "breadth"), _config(item, "selectivity"))
            if item["arm"].lower() == "scan" or key not in scan:
                continue
            comparison_id = _config(item, "comparison_id")
            pair = next((row for row in summary["paired_comparisons"] if row["exp"] == "T3"
                         and row["comparison_id"] == comparison_id and row["denominator"] == item["arm"]), None)
            if pair and pair["status"] == "ok":
                points.append((_number(key[0]), _number(key[1]), pair["ratio"], item))
                finite_ratios.append(pair["ratio"])
        panel_points.append(points)
    if not finite_ratios:
        # All-failure experiments remain a real result; explicitly display their
        # unavailable paired ratios rather than fabricating a numeric heatmap.
        limit = 1.0
    else:
        limit = max(1.0, max(abs(math.log2(value)) for value in finite_ratios))
    for axis, (label, selected), points in zip(axes, facets, panel_points):
        if points:
            for kernel in sorted({point[3]["arm"] for point in points}):
                chosen = [point for point in points if point[3]["arm"] == kernel]
                image = axis.scatter([point[0] for point in chosen], [point[1] for point in chosen],
                                     c=[math.log2(point[2]) for point in chosen], cmap="coolwarm", vmin=-limit, vmax=limit,
                                     marker={"stdpq": "o", "binheap": "s", "quad": "^", "loser": "D"}.get(kernel.split("/")[-1].lower(), "x"),
                                     s=35, alpha=.8, label=kernel)
                used.extend(point[3]["config_id"] for point in chosen)
            figure.colorbar(image, ax=axis, label="log₂(Scan CPU / requested arm CPU)")
            axis.legend(fontsize="xx-small")
        else:
            axis.text(.5, .5, "No complete successful paired ratios", ha="center", transform=axis.transAxes)
        axis.set(xscale="log", xlabel="Subscription breadth k", ylabel="Requested event-leaf selectivity", title=label)
    artifacts += _save(figure, output, "F12_scan_index_crossover", status_note=_status_note(t3) + " Ratios withheld for failed/incomplete pairings.")
    coverage["F12"] = sorted(set(used))

    t5 = experiments["T5"]
    facets = _facet(t5, lambda item: (
        f"snapshot={_config(item, 'snapshot_ts', 'anchor_ts', 'snapshot', 'anchor', 'snapshot_time', default='specified in raw')}; {_cache(item)}"))
    memory_facets = [{"label": label, "configurations": sorted(item["config_id"] for item in selected)}
                     for label, selected in facets]
    figure, axes = _axes(len(facets) * 2, columns=2)
    used = []
    storage_components = ("entries_reserved_bytes", "metadata_reserved_bytes", "sealed_flags_reserved_bytes",
                          "heap_reserved_bytes", "partition_state_reserved_bytes", "partition_list_reserved_bytes", "control_bytes")
    slots = (("live_entries",), ("expired_allocated_entries",), ("open_slack_entries", "open_slack"),
             ("sealed_partial_slack_entries", "sealed_partial_slack"), ("free_entries", "free_block_slots"))
    for index, (label, selected) in enumerate(facets):
        selected = sorted((item for item in selected if item["n_ok"]), key=lambda item: _number(_config(item, "B", "block_entries")))
        left, right = axes[index * 2:index * 2 + 2]
        if selected:
            xs = [_number(_config(item, "B", "block_entries")) for item in selected]
            labels = [str(int(value)) for value in xs]
            base = np.zeros(len(xs))
            for component in storage_components:
                values = np.array([_memory(item, component) for item in selected]) / 2 ** 20
                left.bar(labels, values, bottom=base, label=component.removesuffix("_reserved_bytes"))
                base += values
            for aliases in slots:
                right.plot(xs, [_required_metric(item, *aliases)["median"] for item in selected], marker="o", label=aliases[0].removesuffix("_entries"))
            # The separately measured allocator boundary is not a portable
            # component of Engine::memory. Show it only when an actual linked
            # process measurement is present, preserving signed observations.
            if all(_metric(item, "observed_allocator_overhead_bytes") is not None for item in selected):
                left.plot(labels, [_memory(item, "observed_allocator_overhead_bytes") / 2 ** 20 for item in selected],
                          color="black", marker="x", linestyle="--", label="allocator delta (separate process boundary)")
            left.legend(fontsize="xx-small")
            right.legend(fontsize="xx-small")
            used.extend(item["config_id"] for item in selected)
        else:
            left.text(.5, .5, "No successful observations", ha="center", transform=left.transAxes)
        left.set(xlabel="Entries per block B", ylabel="Requested/reserved index MiB", title=label)
        right.set(xscale="log", yscale="symlog", xlabel="Entries per block B", ylabel="Entry slots", title=label + "; independent recount")
    artifacts += _save(figure, output, "F13_index_memory_slack", status_note=_status_note(t5) + " Requested bytes and observed allocator delta have separate declared boundaries.")
    coverage["F13"] = sorted(set(used))

    manifest = {"schema_version": 1, "figures": [f"F{index:02}" for index in range(6, 14)],
                "input": str(rows_path), "input_sha256": summary["input_sha256"], "summary": str(summary_path),
                "bootstrap_seed": seed, "bootstrap_resamples": 10_000,
                "artifacts": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in artifacts},
                "plotted_configurations": coverage, "status_counts": summary["all_status_counts"],
                "figure_facets": {"F13": memory_facets},
                "all_configurations": [item["config_id"] for item in items],
                "M3": "Seek, scan/entry and memory measurements are preserved in the complete summary; F13 shows the memory/slack component.",
                "scope": "Actual saved observations only; no hardware-counter, latency, session-completeness or universal-winner claim"}
    (output / "p6-figures.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
