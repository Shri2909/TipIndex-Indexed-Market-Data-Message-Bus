"""Prepared-plan T2 identity versions and authoritative duration validation."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('experiment_auditor', ROOT/'scripts/check_p6_experiments.py')
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)


def inputs():
    request = dict(reader_count=2, cache_treatment='repeat-warm', ring_bytes=512,
                   block_entries=64, mode='scan', kernel='stdpq', market_seconds=20,
                   backlog_seconds=20, anchor_ts=36000000000000)
    case = dict(source_identity='fixture-source', workload=dict(id='fixture-workload', seed=17))
    return request, case


def test_version_two_distinguishes_duration_and_source():
    request, case = inputs()
    base = auditor.group_id(request, case, 2)
    assert base != auditor.group_id(dict(request, market_seconds=10, backlog_seconds=10), case, 2)
    assert base != auditor.group_id(request, dict(case, source_identity='different'), 2)
    assert base != auditor.group_id(request, case, 1)


def test_legacy_identity_has_original_fields_only():
    request, case = inputs()
    assert auditor.t2_comparison(request, case, 1) == {
        'exp': 'T2', 'R': 2, 'cache': 'repeat-warm', 'C': 512, 'B': 64}


@pytest.mark.parametrize('version', [True, 0, 3, '2'])
def test_unknown_identity_versions_reject(version):
    request, case = inputs()
    with pytest.raises(ValueError, match='version'):
        auditor.group_id(request, case, version)


def test_declared_duration_must_match_backlog():
    request, case = inputs()
    with pytest.raises(ValueError, match='duration'):
        auditor.group_id(dict(request, market_seconds=10), case, 2)
