#!/usr/bin/env python3
"""Export static F01 study figures from the validated summary, with provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    summary = json.loads(args.summary.read_text())
    if summary["schema"] != "tiplog.f01.poll-summary.v1" or summary["status"] != "passed":
        parser.error("a validated F01 summary is required")
    destination = args.output_dir.resolve()
    if not destination.is_relative_to(root / "results/f01"):
        parser.error("figure directory must be under results/f01")
    destination.mkdir(parents=True, exist_ok=False)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    arms = summary["arms"]
    selections = {}

    def select(label, **criteria):
        rows = [row for row in arms if all(row.get(key) == value for key, value in criteria.items())]
        if len(rows) != 1:
            raise ValueError(f"{label}: expected one arm, found {len(rows)}")
        selections[label] = {"criteria": criteria, "repetitions": rows[0]["repetitions"],
                             "poll_sample_counts": rows[0]["poll_sample_counts"], "service_sample_counts": rows[0]["service_sample_counts"]}
        return rows[0]

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none", "figure.facecolor": "white"})
    exports = []

    def save(fig, stem):
        fig.text(0.5, 0.005, "Shared-host observations; 3 fresh process repetitions. Inspection cap excludes preparation. No hard latency guarantee.",
                 ha="center", fontsize=7, color="#555555")
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        for extension in ("svg", "pdf"):
            path = destination / f"{stem}.{extension}"
            fig.savefig(path, bbox_inches="tight", metadata={"Title": stem, "Creator": "tiplog F01 study"})
            exports.append(path)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    labels = ("legacy", "unlimited", "1000")
    demo = [select("demo-" + budget, records=1000000, case="no-match", shape="small", configured_partitions=1,
                   candidate_every=1, mode="scan", kernel="stdpq", budget=budget, schedule="round-robin", max_outputs=1) for budget in labels]
    axes[0].bar(range(3), [row["poll_p99_ns_median"] / 1e6 for row in demo], color=("#6b7280", "#4b5563", "#2563eb"))
    axes[0].set_xticks(range(3), ("Legacy", "New unlimited", "Budget 1,000"))
    axes[0].set_ylabel("Public-poll p99 (ms)")
    axes[0].set_title("One million nonmatching DATA: Scan")
    axes[0].set_yscale("log")
    for i, row in enumerate(demo):
        calls = int(row["calls_median"])
        unit = "call" if calls == 1 else "calls"
        axes[0].annotate(f"{calls:,} {unit}/rep", (i, row["poll_p99_ns_median"] / 1e6), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)
    budgets = ("legacy", "unlimited", "1", "8", "32", "128", "512", "2048")
    pareto = [select("pareto-" + budget, records=100000, case="no-match", shape="small", configured_partitions=4,
                     candidate_every=1, mode="indexed", kernel="stdpq", budget=budget, schedule="round-robin", max_outputs=1) for budget in budgets]
    for budget, row in zip(budgets, pareto, strict=True):
        x = row["victim_p99_ns_median"] / 1000
        y = row["poll_sum_ratio_to_legacy_median"]
        axes[1].scatter(x, y, color="#2563eb" if budget.isdecimal() else "#6b7280")
        offset = (-8, -13) if budget == "legacy" else (-8, 8) if budget == "unlimited" else (4, 4)
        axes[1].annotate(budget, (x, y), xytext=offset, textcoords="offset points", fontsize=8,
                         ha="right" if budget in ("legacy", "unlimited") else "left")
    axes[1].set(xscale="log", yscale="log", xlabel="Victim service-delay p99 (µs)", ylabel="Replay poll time / legacy", title="100k nonmatches: K4 Indexed cost / responsiveness")
    axes[1].grid(alpha=0.2)
    save(fig, "poll-budget-responsiveness")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    x = list(range(len(budgets)))
    for offset, mode, color in ((-0.18, "scan", "#2563eb"), (0.18, "indexed", "#059669")):
        rows = [select(f"dense-{mode}-{budget}", records=100000, case="dense", shape="small", configured_partitions=4,
                       candidate_every=1, mode=mode, kernel="stdpq", budget=budget, schedule="round-robin", max_outputs=4096) for budget in budgets]
        axes[0].bar([value + offset for value in x], [row["poll_sum_ratio_to_legacy_median"] for row in rows], width=0.34, label=mode, color=color)
    axes[0].set_xticks(x, ("legacy", "nullopt", "1", "8", "32", "128", "512", "2048"), rotation=45)
    axes[0].set(yscale="log", ylabel="Replay poll time / legacy", title="Dense matches; output allowance 4,096")
    axes[0].legend()
    for budget, style in (("1", "-o"), ("128", "-s"), ("unlimited", "-^")):
        rows = [select(f"setup-{k}-{budget}", records=1000, case="no-match", shape="small", configured_partitions=k,
                       candidate_every=1, mode="indexed", kernel="stdpq", budget=budget, schedule="round-robin", max_outputs=1) for k in (64, 256, 4096)]
        axes[1].plot((64, 256, 4096), [row["poll_p50_ns_median"] / 1000 for row in rows], style, label=budget)
    axes[1].set(xscale="log", yscale="log", xlabel="Selected partitions K", ylabel="Public-poll p50 (µs)", title="Preparation remains outside inspection cap")
    axes[1].legend(title="Budget")
    axes[1].grid(alpha=0.2)
    save(fig, "poll-budget-cost")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    control_budgets = ("legacy", "unlimited", "1", "128", "2048")
    for ax, mode in zip(axes, ("scan", "indexed"), strict=True):
        for schedule, style in (("round-robin", "-o"), ("immediate-redrain", "-s")):
            rows = [select(f"control-{mode}-{schedule}-{budget}", records=200000, case="no-match", shape="small", configured_partitions=1,
                           candidate_every=1, mode=mode, kernel="stdpq", budget=budget, schedule=schedule, max_outputs=1) for budget in control_budgets]
            label = "round-robin (one request/poll)" if schedule == "round-robin" else "immediate-redrain (one request/rep)"
            ax.plot(range(len(rows)), [row["victim_p99_ns_median"] / 1e6 for row in rows], style, label=label)
        ax.set_xticks(range(len(control_budgets)), ("legacy", "nullopt", "1", "128", "2048"))
        ax.set(yscale="log", ylabel="Victim service-delay p99 (ms)", xlabel="Inspection budget", title=f"Caller scheduling control: {mode}")
        ax.grid(alpha=0.2)
        ax.legend()
    save(fig, "poll-budget-scheduling")
    manifest = {"schema": "tiplog.f01.poll-figures.v1", "summary": str(args.summary.resolve().relative_to(root)), "summary_sha256": sha(args.summary),
                "script": str(Path(__file__).resolve().relative_to(root)), "script_sha256": sha(__file__), "matplotlib_version": matplotlib.__version__,
                "selections": selections, "outputs": {str(path.relative_to(root)): sha(path) for path in exports}}
    with (destination / "manifest.json").open("x") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    print(json.dumps({"status": "passed", "figures": len(exports), "manifest": str((destination / "manifest.json").relative_to(root))}))


if __name__ == "__main__":
    main()
