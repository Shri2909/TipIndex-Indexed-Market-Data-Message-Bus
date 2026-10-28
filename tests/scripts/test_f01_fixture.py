"""Independent benchmark fixture checks, including simultaneous evidence forgery."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('f01_fixture', ROOT/'scripts/f01_summary.py')
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def fnv(data):
    result = 14695981039346656037
    for byte in data:
        result = (result ^ byte)*1099511628211 % (1 << 64)
    return f'{result:016x}'


def row():
    # One empty-payload message: seq=1, pos=0, topic=3. Its second call
    # confirms the exact output boundary. Timings below are synthetic controls.
    import struct
    digest = {'outputs': 1, 'fnv1a64': fnv(struct.pack('<QQQQ', 1, 0, 3, 0))}
    zero_work = {key: 0 for key in contract._OLD.WORK_FIELDS}
    work = dict(zero_work, records_fetched=1, delivered=1, bytes_inspected=16)
    sample = dict(sample_count=2, p50=10, p95=10, p99=10, max=10, sum=20)
    return dict(schema='tiplog.f01.poll-benchmark.v1', status='ok', reader='replay', correctness='passed',
                records=1, seed=7, case='dense', shape='small', configured_partitions=1, candidate_every=1,
                mode='scan', effective_mode='scan', kernel='stdpq', budget='legacy', schedule='round-robin',
                max_outputs=1, repetition=0, fixture_reserved_bytes=128696, fixture_selected_partitions=1,
                index_reserved_bytes=100000, ring_checkpoint_bytes=24, conservative_topics_bytes=24576,
                selected_partition_count=0, output_digest=digest.copy(), oracle_digest=digest.copy(),
                fixture_candidate_records=1, fixture_priming_records=0, fixture_data_bytes=16,
                fixture_pads_in_range=0, final_checkpoint=dict(after_seq=1, next_pos=16), calls=2,
                max_outputs_in_call=1, zero_output_calls=1, open_work=zero_work, poll_work=work,
                all_work=work.copy(), inspections_used=1, max_inspections_in_call=1, service_calls=2,
                stop_counts={key: 0 for key in contract._OLD.STOPS}, stop_counts_available=False,
                poll_latency_ns=sample.copy(), victim_service_delay_ns=sample.copy(),
                publisher_service_delay_ns=sample.copy(), drain_elapsed_ns=40, drain_cpu_ns=30,
                open_elapsed_ns=1, fixture_build_ns=1, peak_rss_bytes=100000,
                outputs_per_drain_second=25_000_000, fixture_records_per_poll_second=50_000_000)


def test_single_record_independent_digest_and_summary_contract():
    observed = row()
    assert contract.validate(observed) == tuple(observed[x] for x in contract.IDENTITY)


@pytest.mark.parametrize('mutation', ['both_hashes', 'next_pos', 'mode', 'byte_count', 'rate', 'statistics',
                                      'output_type', 'position_type', 'calls_type', 'nonfinite_rate'])
def test_self_consistent_forgery_or_inconsistent_measurement_rejects(mutation):
    observed = row()
    if mutation == 'both_hashes':
        for key in ('output_digest', 'oracle_digest'):
            observed[key]['fnv1a64'] = '0123456789abcdef'
    elif mutation == 'next_pos':
        observed['final_checkpoint']['next_pos'] = 0
    elif mutation == 'mode':
        observed['mode'] = 'indexed'
    elif mutation == 'byte_count':
        for key in ('poll_work', 'all_work'):
            observed[key]['bytes_inspected'] = 24
    elif mutation == 'rate':
        observed['outputs_per_drain_second'] = 0
    elif mutation == 'statistics':
        observed['poll_latency_ns']['sum'] = 30
        observed['fixture_records_per_poll_second'] = 1e9/30
    elif mutation == 'output_type':
        observed['output_digest']['outputs'] = observed['oracle_digest']['outputs'] = True
    elif mutation == 'position_type':
        observed['final_checkpoint']['next_pos'] = 16.0
    elif mutation == 'calls_type':
        observed['calls'] = 2.0
    else:
        observed['outputs_per_drain_second'] = float('nan')
    with pytest.raises(ValueError):
        contract.validate(observed)


def test_leading_pad_is_excluded_from_captured_inspections():
    import struct
    expected = contract.fixture(1, 7, 'dense', 'wrapped-variable', 1, 1)
    assert expected['priming'] == 15
    assert expected['pads'] == expected['pad_bytes'] == 0
    assert expected['next_pos'] == 4112
    assert expected['digest'] == {'outputs': 1, 'fnv1a64': fnv(struct.pack('<QQQQ', 16, 4096, 3, 0))}


def test_internal_pad_is_charged_and_advances_position():
    expected = contract.fixture(2, 7, 'no-match', 'wrapped-variable', 1, 1)
    assert expected['priming'] == 15
    assert expected['pads'] == 1 and expected['pad_bytes'] == 8
    assert expected['data_bytes'] == 40 and expected['next_pos'] == 4120


def test_impossible_large_fixture_rejects_before_iteration():
    with pytest.raises(ValueError, match='resource cap'):
        contract.fixture(2_000_000, 7, 'dense', 'variable', 1, 1)


@pytest.mark.parametrize('k', [12288,65535])
def test_forged_success_cannot_bypass_preparation_resource_cap(k):
    observed = row()
    observed.update(configured_partitions=k, fixture_selected_partitions=k)
    with pytest.raises(ValueError, match='resource cap'):
        contract.validate(observed)


def test_duplicate_keys_and_nonfinite_json_fail_closed():
    for text in ('{"calls":1,"calls":2}', '{"time":NaN}', '{"time":Infinity}'):
        with pytest.raises(ValueError):
            contract.decode(text)
