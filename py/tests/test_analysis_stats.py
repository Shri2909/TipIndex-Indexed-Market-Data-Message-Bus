"""Statistical design checks: pairing, failure retention, seeded uncertainty."""

import json

import pytest

from tiplog_py.analysis.stats import median_summary, paired_ratio, stable_seed
from tiplog_py.analysis.summarize import paired_comparisons, read_rows, summarize_rows, t2_amortized


def test_median_bootstrap_constant_and_reproducible():
    result = median_summary([7] * 10, seed=19)
    assert result["n"] == 10
    assert result["median"] == result["min"] == result["max"] == 7
    assert result["iqr"] == 0
    assert result["ci95_low"] == result["ci95_high"] == 7
    assert result["bootstrap_resamples"] == 10_000
    assert median_summary([1, 2, 3, 20], seed=4) == median_summary([1, 2, 3, 20], seed=4)
    assert stable_seed(5, "a") == stable_seed(5, "a") != stable_seed(5, "b")


def test_paired_resampling_preserves_shared_round_noise():
    # Very large between-round variation cancels exactly under the true pairing.
    numerator = {str(index): [float(2 ** index), float(3 * 2 ** index)] for index in range(12)}
    denominator = {key: [value / 2 for value in values] for key, values in numerator.items()}
    result = paired_ratio(numerator, denominator, seed=3)
    assert result["ratio"] == result["ci95_low"] == result["ci95_high"] == 2
    assert result["bootstrap_unit"] == "whole_paired_round"
    assert result["paired_rounds"] == 12
    assert result["numerator_n"] == result["denominator_n"] == 24


def test_ragged_blocks_keep_all_observations():
    result = paired_ratio({"a": [2], "b": [4, 20]}, {"a": [1], "b": [2, 10]}, seed=7)
    assert result["ratio"] == result["ci95_low"] == result["ci95_high"] == 2
    with pytest.raises(ValueError, match="identical"):
        paired_ratio({"a": [1]}, {"b": [1]}, seed=2)
    with pytest.raises(ValueError, match="positive"):
        paired_ratio({"a": [1]}, {"a": [0]}, seed=2)


def row(arm, rep, status="ok", value=100, warmup=False):
    return {"exp": "T1", "config_id": arm, "comparison_id": "same-state",
            "paired_round_id": f"round-{rep}", "arm": arm, "status": status,
            "cpu_ns": value, "warmup": warmup, "config": {"cache_treatment": "repeat-warm"}}


def test_failed_outcomes_are_retained_and_never_become_fast_speedups():
    rows = [row("Scan", 0, value=100), row("Indexed/BinHeap", 0, "history_expired", value=1),
            row("Scan", 1, value=120), row("Indexed/BinHeap", 1, value=50),
            row("Scan", -1, "crash", warmup=True)]
    summary = summarize_rows(rows)
    scan = next(item for item in summary["configurations"] if item["arm"] == "Scan")
    indexed = next(item for item in summary["configurations"] if item["arm"] != "Scan")
    assert scan["warmup_status_counts"] == {"crash": 1}
    assert scan["metrics"]["cpu_ns"]["n"] == 2
    assert indexed["metrics"]["cpu_ns"]["median"] == 50
    assert indexed["n_non_ok"] == 1
    assert indexed["status_counts"]["history_expired"] == 1
    ratio = paired_comparisons(rows)[0]
    assert ratio["status"] == "incomplete_pairs"
    assert ratio["ratio"] is None and ratio["ci95_low"] is None
    assert ratio["status_counts"]["Indexed/BinHeap"]["history_expired"] == 1


def test_missing_or_unequal_pairings_are_explicit():
    rows = [row("Scan", 0), row("Scan", 1), row("Indexed/BinHeap", 0)]
    ratio = paired_comparisons(rows)[0]
    assert ratio["status"] == "incomplete_pairs"
    assert ratio["unpaired_rounds"] == ["round-1"]
    # Successful, complete matched rounds produce the expected ratio.
    ratio = paired_comparisons([row("Scan", i, value=100 * (i + 1)) for i in range(10)]
                               + [row("Indexed/BinHeap", i, value=50 * (i + 1)) for i in range(10)])[0]
    assert ratio["status"] == "ok" and ratio["ci95_low"] == ratio["ci95_high"] == 2


def test_oracle_failure_excludes_invalid_measurement_and_preserves_engine_status():
    bad = row("Indexed/BinHeap", 0, value=1)
    bad["oracle_validated"] = False
    rows = [row("Scan", 0), bad]
    summary = summarize_rows(rows)
    invalid = next(item for item in summary["configurations"] if item["arm"] == "Indexed/BinHeap")
    assert invalid["raw_status_counts"] == {"ok": 1}
    assert invalid["status_counts"]["oracle_mismatch"] == 1
    assert invalid["n_validation_failed"] == invalid["n_non_ok"] == 1
    assert invalid["n_ok"] == 0 and invalid["metrics"] == {}
    assert paired_comparisons(rows)[0]["ratio"] is None
    bad["status"] = "oracle_mismatch"
    assert summarize_rows(rows)["validation_failed_count"] == 1


def test_incompatible_builds_do_not_become_one_confidence_interval():
    rows = [dict(row("Scan", 0), binary_sha256="a"), dict(row("Scan", 1), binary_sha256="b")]
    with pytest.raises(ValueError, match="incompatible binary_sha256"):
        summarize_rows(rows)


def test_t2_adds_writer_delta_once_and_does_not_clamp_negative_noise():
    result = t2_amortized(1_000_000_000, 300_000_000, 100_000_000, 10)
    assert result["cpu_per_market_second"] == pytest.approx(.1)
    assert result["adjusted_cpu_per_market_second"] == pytest.approx(.12)
    negative = t2_amortized(1_000_000_000, 100_000_000, 200_000_000, 10)
    assert negative["publish_index_delta_cpu_ns"] == -100_000_000
    assert negative["adjusted_cpu_per_market_second"] == pytest.approx(.09)
    with pytest.raises(ValueError):
        t2_amortized(1, 2, 3, 0)
    full_window = t2_amortized(1e9, 3e9, 1.2e9, 10, publish_market_seconds=1800)
    assert full_window["amortized_index_cpu_ns"] == 10_000_000
    assert full_window["adjusted_cpu_per_market_second"] == pytest.approx(.101)


def test_t2_summary_uses_actual_writer_cpu_and_scan_baseline():
    from tiplog_py.analysis.summarize import numeric_metrics
    raw = {"exp": "T2", "arm": "indexed/binheap", "cpu_ns": 1e9,
           "config": {"market_seconds": 10},
           "work": {"publish_index_on_cpu_ns": 3e8, "publish_index_off_cpu_ns": 1e8,
                    "publish_window_market_seconds": 10}}
    assert numeric_metrics(raw)["adjusted_cpu_per_market_second"] == pytest.approx(.12)
    raw["arm"] = "scan"
    assert numeric_metrics(raw)["adjusted_cpu_per_market_second"] == pytest.approx(.1)
    del raw["work"]["publish_window_market_seconds"]
    with pytest.raises(ValueError, match="market-window duration"):
        numeric_metrics(raw)
    with pytest.raises(ValueError, match="negative measured duration"):
        numeric_metrics({"cpu_ns": -1})


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")]])
def test_invalid_observations_rejected(values):
    with pytest.raises(ValueError):
        median_summary(values, seed=0)


def test_input_reader_does_not_relabel_unknown_status(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps(row("Scan", 0)) + "\n")
    assert read_rows(path)[0]["raw_line"] == 1
    path.write_text('{"status": "maybe"}\n')
    with pytest.raises(ValueError, match="outcome"):
        read_rows(path)


def test_frequency_sidecar_flags_only_matching_block_and_attempt_without_rewriting(tmp_path):
    flags = tmp_path / "frequency-flags.json"
    flags.write_text(json.dumps({"samples": [
        {"block": "A", "attempt": 1, "flagged_over_10_percent": True},
        {"block": "A", "attempt": 2, "flagged_over_10_percent": False},
        {"block": "B", "attempt": 1, "flagged_over_10_percent": False}]}))
    observations = [dict(row("Scan", index), block=block, attempt=attempt,
                         frequency_flags_reference=str(flags))
                    for index, (block, attempt) in enumerate((("A", 1), ("A", 2), ("B", 1), ("C", 1)))]
    path = tmp_path / "runs.jsonl"
    raw = "".join(json.dumps(item) + "\n" for item in observations)
    path.write_text(raw)
    loaded = read_rows(path)
    assert [item["noise_flagged"] for item in loaded] == [True, False, False, None]
    assert loaded[0]["noise_observation_status"] == "sidecar-block-attempt"
    assert loaded[-1]["noise_observation_status"] == "missing-or-incomplete-matched-samples"
    summary = summarize_rows(loaded)["configurations"][0]
    assert summary["n_ok"] == 4  # Noise is reported, never silently discarded.
    assert summary["noise_flagged_count"] == 1
    assert summary["noise_observed_count"] == 3
    assert summary["noise_unknown_count"] == 1
    assert path.read_text() == raw


def test_missing_frequency_evidence_remains_unknown_and_explicit_flags_survive(tmp_path):
    path = tmp_path / "runs.jsonl"
    observations = [dict(row("Scan", 0), frequency_flags_reference=str(tmp_path / "missing.json")),
                    dict(row("Scan", 1), noise_flagged=False), row("Scan", 2)]
    path.write_text("".join(json.dumps(item) + "\n" for item in observations))
    loaded = read_rows(path)
    assert [item["noise_flagged"] for item in loaded] == [None, False, None]
    assert loaded[0]["noise_observation_status"] == "missing-sidecar"
    summary = summarize_rows(loaded)["configurations"][0]
    assert summary["noise_flagged_count"] == 0
    assert summary["noise_unknown_count"] == 2


def test_failed_measurement_command_does_not_make_a_valid_timing_or_ratio():
    bad = dict(row("Indexed/BinHeap", 0, value=1), measurement_command_ok=False,
               oracle_validated=True)
    observations = [row("Scan", 0), bad]
    item = next(item for item in summarize_rows(observations)["configurations"]
                if item["arm"] == "Indexed/BinHeap")
    assert item["raw_status_counts"] == {"ok": 1}
    assert item["status_counts"]["invalid_config"] == 1
    assert item["n_ok"] == 0 and item["metrics"] == {}
    assert paired_comparisons(observations)[0]["status"] == "incomplete_pairs"


def test_t_frequency_annotations_match_process_repetition_and_warmup_exactly(tmp_path):
    flags = tmp_path / "frequency-flags.json"
    flags.write_text(json.dumps({"annotations": [
        {"config_id": "Scan", "process_round_id": "p1", "rep": 0,
         "warmup": False, "frequency_noisy": True},
        {"config_id": "Scan", "process_round_id": "p1", "rep": 0,
         "warmup": True, "frequency_noisy": False},
        {"config_id": "Scan", "process_round_id": "p2", "rep": 0,
         "warmup": False, "frequency_noisy": False},
        {"config_id": "Scan", "process_round_id": "p1", "rep": 1,
         "warmup": False, "frequency_noisy": None}]}))
    observations = [dict(row("Scan", rep, warmup=warmup), process_round_id=process,
                         rep=rep, frequency_flags_reference=str(flags))
                    for process, rep, warmup in (("p1", 0, False), ("p1", 0, True),
                                                 ("p2", 0, False), ("p1", 1, False),
                                                 ("p3", 0, False))]
    path = tmp_path / "runs.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in observations))
    loaded = read_rows(path)
    assert [item["noise_flagged"] for item in loaded] == [True, False, False, None, None]
    assert loaded[0]["noise_observation_status"] == "sidecar-process-observation"
    assert loaded[-1]["noise_observation_status"] == "missing-or-duplicate-process-annotation"
    summary = summarize_rows(loaded)["configurations"][0]
    assert summary["noise_flagged_count"] == 1
    assert summary["noise_observed_count"] == 2
    assert summary["noise_unknown_count"] == 2
