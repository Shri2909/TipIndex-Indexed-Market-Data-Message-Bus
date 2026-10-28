"""Figure pipeline tests use explicit synthetic fixtures in pytest temp storage.

They validate schemas and missing-data behavior, and are never saved as actual
project measurements or performance evidence.
"""

import json
import math

import pytest

from tiplog_py.figures import tip
from tiplog_py.figures.tip import build


def fixture_rows():
    rows = []

    def add(exp, name, config, *, cpu=100, item=None, work=None, comparison=None, status="ok"):
        for rep in range(3):
            row = {"exp": exp, "config_id": name, "config": config, "status": status,
                   "cpu_ns": cpu * (rep + 1), "wall_ns": cpu * (rep + 1),
                   "paired_round_id": f"fixture-{rep}", "comparison_id": comparison,
                   "warmup": False, "rep": rep, "work": work or {}}
            if item is not None:
                row["item_cpu_ns"] = item * (rep + 1)
            rows.append(row)

    for exp in ("M1", "M1-touch"):
        for pattern in ("uniform", "geometric1", "geometric4"):
            for k in (1, 4):
                for kernel in ("stdpq", "binheap"):
                    add(exp, f"{exp}/{pattern}/{k}/{kernel}", dict(k=k, kernel=kernel, pattern=pattern), item=k)
    for p in (1, 100):
        for enabled in (False, True):
            add("M2", f"M2/{p}/{enabled}", dict(P=p, B=256, payload=64, distribution="uniform", index_enabled=enabled), item=2)
    add("M3", "M3/B64", dict(B=64), work=dict(seek_ns=2, scan_ns_per_entry=1))
    for k in (1, 10):
        for mode in ("scan", "indexed"):
            common = dict(mode=mode, kernel="binheap", cache_treatment="repeat-warm")
            add("T1", f"T1/{k}/{mode}", dict(common, breadth=k, name=f"BOOK-top{k}", backlog_seconds=10),
                work=dict(entries_visited=0 if mode == "scan" else k, records_fetched=100 if mode == "scan" else k, bytes_inspected=6400),
                comparison=f"T1/{k}")
            add("T2", f"T2/{k}/{mode}", dict(common, R=k, market_seconds=10),
                work=dict(publish_index_on_cpu_ns=200, publish_index_off_cpu_ns=100, publish_window_market_seconds=1800), comparison=f"T2/{k}")
    arms = [("scan", "stdpq")] + [(mode, kernel) for mode in ("indexed", "auto")
                                  for kernel in ("stdpq", "binheap", "quad", "loser")]
    for k in (1, 10):
        for selectivity in (.1, 1):
            for index, (mode, kernel) in enumerate(arms):
                config = dict(mode=mode, kernel=kernel, cache_treatment="repeat-warm",
                              k=k, selectivity=selectivity, P=10, Z=0, L=1)
                add("T3", f"T3/{k}/{selectivity}/{mode}/{kernel}", config,
                    cpu=200 if mode == "scan" else 80 + 10 * index + k * selectivity,
                    comparison=f"T3/{k}/{selectivity}",
                    status="invalid_config" if (k, selectivity, mode, kernel) == (10, 1, "indexed", "quad") else "ok")
    for b in (64, 256):
        work = dict(entries_reserved_bytes=1024, metadata_reserved_bytes=32, sealed_flags_reserved_bytes=1,
                    heap_reserved_bytes=24, partition_state_reserved_bytes=64, partition_list_reserved_bytes=16,
                    control_bytes=8, live_entries=100, expired_allocated_entries=10, open_slack=20,
                    sealed_partial_slack=10, free_block_slots=116, observed_allocator_overhead_bytes=7)
        add("T5", f"T5/{b}", dict(B=b, snapshot="fixture-time"), work=work)
        # Actual runner keys, with duplicate B values across anchor/cache
        # strata: these must remain distinct panels instead of mixed bars.
        for anchor in (34500000000000, 35100000000000):
            for cache in ("repeat-warm", "scratch-thrashed"):
                add("T5", f"T5/{b}/{anchor}/{cache}",
                    dict(B=b, snapshot_ts=anchor, anchor_ts=anchor, cache_treatment=cache),
                    work=work)
    return rows


def test_all_figures_use_only_supplied_rows_and_preserve_input_identity(tmp_path, monkeypatch):
    captured = {}
    original_save = tip._save

    def inspect_save(figure, output, name, **kwargs):
        if name.startswith("F12"):
            axis = next(axis for axis in figure.axes if axis.get_xlabel().startswith("Subscription breadth k"))
            colored, unavailable = {}, []
            for collection in axis.collections:
                positions = [tuple(float(value) for value in point) for point in collection.get_offsets()]
                colors = collection.get_array()
                if colors is None:
                    unavailable.extend(positions)
                else:
                    colored.update(zip(positions, [float(value) for value in colors]))
            captured["F12"] = dict(colored=colored, unavailable=unavailable,
                                   xscale=axis.get_xscale(),
                                   xlabels=[label.get_text() for label in axis.get_xticklabels()],
                                   ylabels=[label.get_text() for label in axis.get_yticklabels()])
        if name.startswith("F13"):
            captured["F13"] = dict(titles=[axis.get_title() for axis in figure.axes],
                slot_lowers=[axis.get_ylim()[0] for axis in figure.axes if axis.get_ylabel() == "Entry slots"])
        result = original_save(figure, output, name, **kwargs)
        if name.startswith("F13"):
            captured["F13"]["footer"] = figure.texts[-1].get_text()
            captured["F13"]["original_footer"] = kwargs["status_note"]
        return result

    monkeypatch.setattr(tip, "_save", inspect_save)
    path = tmp_path / "explicit-synthetic-fixture.jsonl"
    rows = fixture_rows()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    output = tmp_path / "figures"
    result = build(path, output, summary_path=tmp_path / "derived/summary.json")
    assert result["figures"] == [f"F{index:02}" for index in range(6, 14)]
    assert len(result["artifacts"]) == 16
    assert all(value for value in result["artifacts"].values())
    assert all((tmp_path / "figures" / f"{name}.png").exists() for name in (
        "F06_merge_cost_vs_k", "F07_merge_run_length", "F08_publish_index_cost",
        "F09_catchup_breadth", "F10_replay_work", "F11_many_readers_cpu",
        "F12_scan_index_crossover", "F13_index_memory_slack"))
    summary = json.loads((tmp_path / "derived/summary.json").read_text())
    assert summary["row_count"] == len(rows)
    assert summary["input_sha256"] == result["input_sha256"]
    assert summary["all_status_counts"] == {"invalid_config": 3, "ok": len(rows) - 3}
    assert (tmp_path / "derived/tip-outcomes.csv").exists()
    assert (tmp_path / "derived/tip-paired-ratios.csv").exists()
    facets = result["figure_facets"]["F13"]
    assert len(facets) == 5  # Four real-schema strata plus the legacy fixture.
    for anchor in (34500000000000, 35100000000000):
        for cache in ("repeat-warm", "scratch-thrashed"):
            facet = next(item for item in facets if item["label"] == f"snapshot={anchor}; {cache}")
            assert facet["configurations"] == sorted(f"T5/{b}/{anchor}/{cache}" for b in (64, 256))
    assert next(item for item in facets if "fixture-time" in item["label"])["configurations"] == ["T5/256", "T5/64"]
    assert all(value == 0 for value in captured["F13"]["slot_lowers"])
    assert any("\n" in title for title in captured["F13"]["titles"])
    assert "\n" in captured["F13"]["footer"]
    assert captured["F13"]["footer"].split() == captured["F13"]["original_footer"].split()

    panel = result["figure_facets"]["F12"][0]
    points = panel["points"]
    assert len(points) == 32  # Four true cells, each retaining all eight arms.
    assert len({(point["x"], point["y"]) for point in points}) == len(points)
    assert panel["k_values"] == [1, 10] and panel["selectivity_values"] == [.1, 1]
    assert captured["F12"]["xscale"] == "linear"
    assert captured["F12"]["xlabels"] == ["1", "10"]
    assert captured["F12"]["ylabels"] == ["0.1", "1"]
    assert len(captured["F12"]["colored"]) == 31 and len(captured["F12"]["unavailable"]) == 1
    configs = {item["config_id"]: item for item in summary["configurations"] if item["exp"] == "T3"}
    pairs = {(item["comparison_id"], item["denominator"]): item
             for item in summary["paired_comparisons"] if item["exp"] == "T3"}
    for point in points:
        pair = pairs[(configs[point["config_id"]]["comparison_id"], point["arm"])]
        assert point["ratio"] == pair["ratio"]  # Ratios are unchanged, not averaged or displaced numerically.
        position = (point["x"], point["y"])
        if point["ratio"] is None:
            assert position in captured["F12"]["unavailable"]
            assert point["paired_status"] == "incomplete_pairs" and point["status_counts"] == {"invalid_config": 3}
        else:
            assert math.isclose(captured["F12"]["colored"][position], math.log2(pair["ratio"]))
    selected = list(configs.values())
    assert tip._crossover_panel(selected, summary["paired_comparisons"]) == tip._crossover_panel(
        list(reversed(selected)), list(reversed(summary["paired_comparisons"])))
    with pytest.raises(ValueError, match="ambiguous F12 cell/arm"):
        tip._crossover_panel(selected + [next(item for item in selected if item["arm"] != "scan")],
                             summary["paired_comparisons"])


def test_factorized_legends_keep_every_curve_ci_and_stable_arm_color():
    from matplotlib.legend import Legend

    arms = ["scan"] + [f"{mode}/{kernel}" for mode in ("indexed", "auto")
                       for kernel in ("stdpq", "binheap", "quad", "loser")]
    families = ["BOOK-top", "BOOK-median", "BOOK-random", "TAPE-top", "all-trades", "full-stream"]
    items = []
    for arm_index, arm in enumerate(arms):
        for family_index, family in enumerate(families):
            for k in (1, 10):
                value = 10 + arm_index * 100 + family_index * 10 + k
                items.append(dict(config_id=f"{arm}/{family}/{k}", n_ok=1, k=k,
                    series=f"{arm}; {family}",
                    metric=dict(median=value, ci95_low=value - 1, ci95_high=value + 2)))
    figure, axes = tip.plt.subplots(1, 2, figsize=(9.4, 3.5))
    try:
        used = tip._lines(axes[0], items, lambda item: item["k"], lambda item: item["metric"], lambda item: item["series"])
        assert set(used) == {item["config_id"] for item in items}
        assert len(axes[0].containers) == 54  # All arm/family curves and their CIs remain.
        colors = {}
        for container in axes[0].containers:
            arm, family = container.get_label().split("; ", 1)
            curve = container.lines[0]
            expected = sorted((item for item in items if item["series"] == container.get_label()), key=lambda item: item["k"])
            assert list(curve.get_xdata()) == [item["k"] for item in expected]
            assert list(curve.get_ydata()) == [item["metric"]["median"] for item in expected]
            for segment, item in zip(container.lines[2][0].get_segments(), expected):
                assert list(segment[:, 1]) == [item["metric"]["ci95_low"], item["metric"]["ci95_high"]]
            colors.setdefault(arm, curve.get_color())
            assert colors[arm] == curve.get_color()
        assert len(set(colors.values())) == 9
        legends = [child for child in axes[0].get_children() if isinstance(child, Legend)]
        assert sorted(len(legend.get_texts()) for legend in legends) == [6, 9]

        # T2 draws each cost component in a separate call; both legends must be
        # accumulated without losing earlier lines or retaining stale legends.
        for suffix in ("recovery only", "+ actual writer delta"):
            selected = [dict(item, series=item["series"].split("; ", 1)[0] + "; " + suffix)
                        for item in items if item["series"].endswith("; BOOK-top")]
            tip._lines(axes[1], selected, lambda item: item["k"], lambda item: item["metric"], lambda item: item["series"])
        assert len(axes[1].containers) == 18
        legends = [child for child in axes[1].get_children() if isinstance(child, Legend)]
        assert sorted(len(legend.get_texts()) for legend in legends) == [2, 9]
        assert all(container.lines[0].get_color() == colors[container.get_label().split("; ", 1)[0]]
                   for container in axes[1].containers)
    finally:
        tip.plt.close(figure)


def test_missing_campaign_does_not_generate_placeholder_figures(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    output = tmp_path / "figures"
    with pytest.raises(ValueError, match="require actual M1"):
        build(path, output, summary_path=tmp_path / "derived/summary.json")
    assert not list(output.glob("F*.png"))
