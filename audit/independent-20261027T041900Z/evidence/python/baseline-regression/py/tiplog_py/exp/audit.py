"""Auditable P6 repetition, correctness, frequency and pilot checks."""
from __future__ import annotations
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics


def pilot_cv(rows: list[dict], *, limit: float) -> dict:
    sample = [float(row.get('item_cpu_ns', row.get('cpu_ns'))) for row in rows
              if not row.get('warmup') and row.get('status') == 'ok']
    if len(sample) < 30:
        raise ValueError('pilot requires at least30 valid individual observations')
    mean = statistics.mean(sample)
    cv = statistics.stdev(sample)/mean if mean else None
    return {'n': len(sample), 'mean': mean, 'sample_stdev': statistics.stdev(sample),
            'coefficient_of_variation': cv, 'threshold': limit,
            'response_required': cv is None or cv > limit,
            'decision': 'increase repetitions or fix environment before protocol freeze'
                        if cv is None or cv > limit else 'retain declared baseline repetitions'}


def frequency_flags(rows: list[dict]) -> dict:
    def samples(row):
        return [value for value in row.get('frequency_samples_khz',
                [row.get('freq_start_khz'),row.get('freq_end_khz')]) if value]
    frequencies = [float(value) for row in rows for value in samples(row)]
    median = statistics.median(frequencies) if frequencies else None
    annotations = []
    for row in rows:
        observed = samples(row)
        noisy = any(abs(value-median) > .1*median for value in observed) if median and observed else None
        annotations.append({'config_id': row['config_id'], 'process_round_id': row.get('process_round_id'),
                            'rep': row.get('rep'), 'warmup': row.get('warmup'), 'frequency_noisy': noisy,
                            'observed_khz': observed})
    return {'session_median_khz': median, 'rule': '>10% from session median; all rows retained',
            'flagged_rows': sum(item['frequency_noisy'] is True for item in annotations),
            'unknown_rows': sum(item['frequency_noisy'] is None for item in annotations),
            'annotations': annotations}


def acceptance(rows: list[dict], *, measured_repetitions=10, expected_manifest=None) -> dict:
    """Audit controls and exact repetitions for supplied rows.

    expected_manifest maps every expected config_id to its measured repetition
    labels (e.g. {'arm-a': list(range(10))}). Without it, campaign coverage is
    explicitly unknown; the independent final campaign audit remains required.
    """
    if type(measured_repetitions) is not int or measured_repetitions < 1:
        raise ValueError('measured repetitions must be positive')
    if expected_manifest is not None:
        for identity, repetitions in expected_manifest.items():
            if (not isinstance(identity, str) or not isinstance(repetitions, list) or not repetitions or
                    any(type(rep) is not int or rep < 0 for rep in repetitions) or
                    len(set(repetitions)) != len(repetitions)):
                raise ValueError('expected manifest requires config ids and unique nonnegative repetition lists')
    groups = defaultdict(list)
    for row in rows: groups[row['config_id']].append(row)
    checks = []
    for identity, group in sorted(groups.items()):
        measured = [row for row in group if not row.get('warmup')]
        warmups = [row for row in group if row.get('warmup')]
        process_ids = {row.get('process_round_id') for row in measured}
        pids = {row.get('process_pid') for row in measured}
        oracle_valid = all(row.get('oracle_validated') is True and row.get('oracle', {}).get('status') == 'passed'
                           for row in group)
        if group[0]['exp'] == 'T2':
            oracle_valid = all(row.get('oracle', {}).get('status') == 'passed' for row in group)
        affinity = all(row.get('cpu_start') == 2 and row.get('cpu_end') == 2
                       for row in group if row.get('status') != 'invalid_config')
        command_valid = all(row.get('measurement_command_ok') is True for row in group)
        expected_reps = (expected_manifest.get(identity, []) if expected_manifest is not None
                         else list(range(measured_repetitions)))
        actual_reps = [row.get('rep') for row in measured]
        repetitions_valid = (all(type(rep) is int for rep in actual_reps) and
                             sorted(actual_reps) == sorted(expected_reps) and
                             len(warmups) == 1 and warmups[0].get('rep') == -1)
        passed = (repetitions_valid and len(warmups) == 1 and
                  len(process_ids) == len(measured) and len(pids) == len(measured) and
                  None not in process_ids and None not in pids and oracle_valid and affinity and command_valid)
        checks.append({'config_id': identity, 'status': 'passed' if passed else 'failed',
                       'measured': len(measured), 'warmups': len(warmups),
                       'distinct_process_ids': len(process_ids), 'distinct_pids': len(pids),
                       'oracle_validated': oracle_valid, 'affinity_cpu2': affinity,
                       'measurement_commands_valid':command_valid, 'repetition_labels_valid':repetitions_valid,
                       'outcomes': dict(Counter(row['status'] for row in group))})
    missing = sorted(set(expected_manifest or {}) - set(groups))
    unexpected = sorted(set(groups) - set(expected_manifest)) if expected_manifest is not None else []
    return {'status': 'passed' if checks and not missing and not unexpected and all(check['status'] == 'passed' for check in checks) else 'failed',
            'scope':'expected-manifest' if expected_manifest is not None else 'supplied-rows-only',
            'campaign_coverage_verified':expected_manifest is not None and not missing and not unexpected,
            'missing_configurations':missing, 'unexpected_configurations':unexpected,
            'configurations': len(checks), 'checks': checks,
            'outcomes_including_warmup': dict(Counter(row['status'] for row in rows))}


def audit_file(path: Path, *, measured_repetitions=10, expected_manifest=None):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    result = acceptance(rows, measured_repetitions=measured_repetitions, expected_manifest=expected_manifest)
    path.with_name('acceptance.json').write_text(json.dumps(result, indent=2)+'\n')
    path.with_name('frequency-flags.json').write_text(json.dumps(frequency_flags(rows), indent=2)+'\n')
    return result
