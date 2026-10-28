"""Figure pipeline tests use explicit synthetic fixtures in pytest temp storage.

They validate schemas and missing-data behavior, and are never saved as actual
project measurements or performance evidence.
"""

import json

import pytest

from tiplog_py.figures.tip import build


def fixture_rows():
    rows = []

    def add(exp, name, config, *, cpu=100, item=None, work=None, comparison=None):
        for rep in range(3):
            row = {"exp": exp, "config_id": name, "config": config, "status": "ok",
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
            for selectivity in (.1, 1):
                add("T3", f"T3/{k}/{selectivity}/{mode}", dict(common, k=k, selectivity=selectivity, P=10, Z=0, L=1),
                    cpu=200 if mode == "scan" else 100, comparison=f"T3/{k}/{selectivity}")
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


def test_all_figures_use_only_supplied_rows_and_preserve_input_identity(tmp_path):
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
    assert summary["all_status_counts"] == {"ok": len(rows)}
    assert (tmp_path / "derived/tip-outcomes.csv").exists()
    assert (tmp_path / "derived/tip-paired-ratios.csv").exists()
    facets = result["figure_facets"]["F13"]
    assert len(facets) == 5  # Four real-schema strata plus the legacy fixture.
    for anchor in (34500000000000, 35100000000000):
        for cache in ("repeat-warm", "scratch-thrashed"):
            facet = next(item for item in facets if item["label"] == f"snapshot={anchor}; {cache}")
            assert facet["configurations"] == sorted(f"T5/{b}/{anchor}/{cache}" for b in (64, 256))
    assert next(item for item in facets if "fixture-time" in item["label"])["configurations"] == ["T5/256", "T5/64"]


def test_missing_campaign_does_not_generate_placeholder_figures(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    output = tmp_path / "figures"
    with pytest.raises(ValueError, match="require actual M1"):
        build(path, output, summary_path=tmp_path / "derived/summary.json")
    assert not list(output.glob("F*.png"))
