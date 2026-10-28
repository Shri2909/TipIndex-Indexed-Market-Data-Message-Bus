"""Regenerate available accepted figure families from their saved input manifests."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def rows(path):
    with Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def save(figure, output, name):
    figure.tight_layout()
    for extension in ("png", "pdf"):
        figure.savefig(output / f"{name}.{extension}", dpi=160)
    plt.close(figure)


def build(data_dir: Path, output: Path, prefix: str, counts: Path):
    output.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(counts.read_text())
    by_type = metadata["by_type"]
    kinds = sorted(by_type, key=lambda kind: (-by_type[kind]["count"], kind))
    figure, axes = plt.subplots(1, 2, figsize=(11, 4))
    for axis, metric in zip(axes, ("count", "payload_bytes")):
        axis.bar(kinds, [by_type[kind][metric] for kind in kinds])
        axis.set(xlabel="ITCH type", ylabel=metric.replace("_", " "), title="Full-day message mix")
        axis.set_yscale("log")
    save(figure, output, "F01_itch_type_mix")

    partitions = [row for row in rows(data_dir / f"{prefix}_full_day_partition_volumes.csv")
                  if not row["partition"].split("/")[1].startswith("_")]
    figure, axes = plt.subplots(2, 2, figsize=(10, 8))
    for index, metric in enumerate(("count", "payload_bytes")):
        values = np.sort(np.array([int(row[metric]) for row in partitions]))
        if len(values) and values.sum():
            unique_values, first_indices = np.unique(values, return_index=True)
            # At repeated volumes, all equal-valued symbols count toward P(V >= x).
            axes[index, 0].step(unique_values, (len(values) - first_indices) / len(values), where="post")
            axes[index, 0].set(xscale="log", yscale="log", xlabel=metric.replace("_", " "), ylabel="P(volume ≥ x)", title="Per-symbol CCDF")
            axes[index, 1].plot(np.arange(len(values) + 1) / len(values), np.concatenate(([0.0], np.cumsum(values) / values.sum())))
            axes[index, 1].plot([0, 1], [0, 1], linestyle="--", color="gray")
            axes[index, 1].set(xlabel="Fraction of symbols", ylabel=f"Fraction of {metric.replace('_', ' ')}", title="Lorenz curve")
    save(figure, output, "F02_symbol_volume_skew")

    families = rows(data_dir / f"{prefix}_full_day_family_volumes.csv")
    topics = rows(data_dir / f"{prefix}_full_day_topic_volumes.csv")
    ranked = sorted(partitions, key=lambda row: (-int(row["count"]), row["partition"]))
    selected = [row["partition"] for row in ranked[:20]]
    family_names = sorted({row["family"] for row in families})
    lookup = {(row["partition"], row["family"]): int(row["payload_bytes"]) for row in families}
    figure, axes = plt.subplots(1, 2, figsize=(13, 5))
    base = np.zeros(len(selected))
    for family in family_names:
        heights = np.array([lookup.get((partition, family), 0) for partition in selected], dtype=float)
        totals = np.array([int(row["payload_bytes"]) for row in ranked[:20]])
        heights = np.divide(heights, totals, out=np.zeros_like(heights), where=totals != 0)
        axes[0].bar([partition.split("/")[1] for partition in selected], heights, bottom=base, label=family)
        base += heights
    axes[0].tick_params(axis="x", labelrotation=90)
    axes[0].set(ylabel="Share of payload bytes", title="Top-20 symbols: family composition")
    axes[0].legend(fontsize="x-small")
    modify = {partition: lookup.get((partition, "modify"), 0) for partition in selected}
    execution = {partition: 0 for partition in selected}
    for row in topics:
        if row["partition"] in execution and row["type"] in ("E", "C"):
            execution[row["partition"]] += int(row["payload_bytes"])
    ratios = [execution[partition] / modify[partition] if modify[partition] else 0 for partition in selected]
    axes[1].bar([partition.split("/")[1] for partition in selected], ratios)
    axes[1].tick_params(axis="x", labelrotation=90)
    axes[1].set(ylabel="E+C bytes / modify bytes", ylim=(0, 1), title="Execution share of modify family")
    save(figure, output, "F03_family_composition")

    run_rows = rows(data_dir / f"{prefix}_full_day_run_lengths.csv")
    rate_rows = rows(data_dir / f"{prefix}_full_day_per_second.csv")
    figure, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].loglog([int(row["run_length"]) for row in run_rows], [int(row["runs"]) for row in run_rows], marker=".", linestyle="none")
    axes[0].set(xlabel="Consecutive same-partition messages", ylabel="Runs", title="Canonical source order")
    axes[1].plot([int(row["second_since_midnight"]) / 3600 for row in rate_rows], [int(row["count"]) for row in rate_rows], linewidth=.7)
    axes[1].set(xlabel="Exchange hour since midnight", ylabel="Messages / second", title="Full-day burst profile")
    save(figure, output, "F04_runs_and_bursts")

    complexity = rows(data_dir / f"{prefix}_full_day_partition_complexity.csv")
    figure, axes = plt.subplots(1, 2, figsize=(12, 4))
    node_values = [int(row["nodes"]) for row in complexity]
    if node_values:
        axes[0].hist(node_values, bins=np.arange(min(node_values) - .5, max(node_values) + 1.5), rwidth=.8)
    axes[0].set(xlabel="|V| (positive-subtree tree)", ylabel="Partitions", title="Partition tree sizes")
    for workload in ("W0_raw", "W1_effective", "W2_effective", "W3_effective"):
        values, frequencies = np.unique([int(row[f"b_{workload}"]) for row in complexity], return_counts=True)
        axes[1].plot(values, frequencies, marker="o", label=workload)
    axes[1].set(xlabel="Active class count b (see CSV raw/effective)", ylabel="Partitions", yscale="log", title="Per-workload class counts")
    axes[1].legend(fontsize="small")
    save(figure, output, "F05_tree_and_class_sizes")
    manifest = {"figures": [f"F{index:02}" for index in range(1, 6)],
                "inputs": {"data_dir": str(data_dir), "counts": str(counts), "prefix": prefix},
                "selection": "Full-day totals; F03 top-20 symbols by message count, deterministic ties by path",
                "scope": "P1 F01–F05 only; later-phase figures have no inputs and are not claimed generated"}
    (output / "p1-figures.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("results/data"))
    parser.add_argument("--output", type=Path, default=Path("results/figures"))
    parser.add_argument("--prefix", default="itch_20191230")
    parser.add_argument("--counts", type=Path, default=Path("results/data/itch_20191230_counts.json"))
    parser.add_argument("--tip-rows", type=Path,
                        help="Actual consolidated P6 observations; excludes pilot/training")
    parser.add_argument("--summary-output", type=Path,
                        help="P6 summary destination; default is OUTPUT/../derived/tip-summary.json")
    parser.add_argument("--evidence-root", type=Path,
                        help="Declared workspace for relative frequency sidecar references")
    parser.add_argument("--seed", type=int, default=20191230)
    args = parser.parse_args(argv)
    manifests = {"P1": build(args.data_dir, args.output, args.prefix, args.counts)}
    tip_manifest = Path("results/p6/analysis-inputs.json")
    if args.tip_rows is not None or tip_manifest.exists():
        from .tip import build as build_tip
        path = args.tip_rows or Path(json.loads(tip_manifest.read_text())["rows_path"])
        manifests["P6"] = build_tip(path, args.output, seed=args.seed,
                                    summary_path=args.summary_output or args.output.parent / "derived/tip-summary.json",
                                    evidence_root=args.evidence_root)
    elif Path("results/p6/phase-gate.json").exists():
        raise ValueError("P6 gate exists without its required figure input manifest")
    layout_manifest = Path("results/p7/analysis-inputs.json")
    if layout_manifest.exists():
        from .layout import build as build_layout
        layout_inputs = json.loads(layout_manifest.read_text())
        manifests["P7"] = build_layout(layout_inputs["summary"], layout_inputs["global"],
                                       layout_inputs["worked_example"], args.output,
                                       runtime_path=layout_inputs.get("runtime"))
    elif Path("results/p7/phase-gate.json").exists():
        raise ValueError("P7 gate exists without its required figure input manifest")
    print(json.dumps(manifests, sort_keys=True))


if __name__ == "__main__":
    main()
