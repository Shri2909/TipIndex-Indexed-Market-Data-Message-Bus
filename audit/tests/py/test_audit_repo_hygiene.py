"""Audit: test-suite hygiene and small CLI/statistics contracts."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(os.environ.get("TIPLOG_ROOT", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / "py"))

from tiplog_py.analysis.stats import median_summary, paired_ratio  # noqa: E402
from tiplog_py.itch.__main__ import time_ns  # noqa: E402


def test_red03_project_tests_do_not_depend_on_working_directory():
    """RED-03 (AUD-006). The suite's own config sets pythonpath/testpaths
    relative to py/pytest.ini, so running it from py/ is a supported
    invocation. Baseline: test_exp_protocol.py loads 'configs/P6/matrix.toml'
    relative to the CWD and fails with FileNotFoundError from py/."""
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               MPLCONFIGDIR=os.environ.get("MPLCONFIGDIR", "/tmp"))
    target = "tests/test_exp_protocol.py::test_subscriptions_overlap_normalization_and_manifest_defaults"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
                            cwd=ROOT / "py", env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-2000:]


def test_bootstrap_is_seeded_and_paired_rounds_are_required():
    values = [5.0, 7.0, 6.0, 9.0, 8.0, 6.5]
    assert median_summary(values, seed=3) == median_summary(values, seed=3)
    summary = median_summary(values, seed=3)
    assert summary["ci95_low"] <= summary["median"] <= summary["ci95_high"]
    with pytest.raises(ValueError):
        paired_ratio({"a": [1.0]}, {"b": [1.0]}, seed=1)
    with pytest.raises(ValueError):
        paired_ratio({"a": [1.0]}, {"a": [0.0]}, seed=1)
    ratio = paired_ratio({"a": [2.0], "b": [4.0]}, {"a": [1.0], "b": [2.0]}, seed=1)
    assert ratio["ratio"] == 2.0 and ratio["ci95_low"] == ratio["ci95_high"] == 2.0


@pytest.mark.parametrize("text,expected", [
    ("09:30:00", 34_200_000_000_000),
    ("09:30:00.5", 34_200_500_000_000),
    ("24:00:00", 86_400_000_000_000),
    ("0", 0),
])
def test_time_parser_accepts_documented_forms(text, expected):
    assert time_ns(text) == expected


@pytest.mark.parametrize("text", ["24:00:01", "09:60:00", "09:30:00.1234567890", "-1", "1e3", "86400000000001"])
def test_time_parser_rejects_out_of_contract_forms(text):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        time_ns(text)


def test_time_parser_unicode_digit_observation():
    """Observation (INFO): str.isdecimal()/int() accept non-ASCII decimal
    digits, so '٣' (ARABIC-INDIC THREE) parses as 3 ns. Recorded, not a defect
    in itself; documented contract says 'integer nanoseconds'."""
    assert time_ns("٣") == 3
