"""Deterministic training-only selection of a frozen Auto policy."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import statistics
import numpy as np


def calibrate(rows: list[dict], config: dict, output: Path) -> dict:
    training = [row for row in rows if not row.get('warmup') and row.get('config', {}).get('split') == 'training']
    if not training: raise ValueError('no declared training observations')
    groups = {}
    for row in training:
        key = row['comparison_id']
        groups.setdefault(key, []).append(row)
    costs = []
    for maximum in config['max_partitions_candidates']:
        for fraction in config['max_fraction_candidates']:
            total = 0.0
            for comparison, group in sorted(groups.items()):
                if any(row['status'] != 'ok' for row in group):
                    raise ValueError('training cohort has an incomplete or failed arm')
                scan = [row for row in group if row['config']['mode'] == 'scan']
                indexed = [row for row in group if row['config']['mode'] == 'indexed' and row['config']['kernel'] == 'binheap']
                if not scan or not indexed: raise ValueError('training cohort lacks Scan/BinHeap arms')
                sample = indexed[0]
                count = sample.get('selected_partitions', sample.get('work', {}).get('selected_partitions'))
                density = sample.get('estimated_index_fraction', sample.get('work', {}).get('estimated_index_fraction'))
                if count is None or density is None:
                    raise ValueError('missing actual Auto decision inputs in training observations')
                estimate, range_records = sample.get('estimated_entries'), sample.get('range_records')
                within_fraction = (np.longdouble(estimate) <= np.longdouble(range_records)*np.longdouble(float(fraction))
                                   if estimate is not None and range_records is not None else density <= fraction)
                chosen = indexed if count <= maximum and count <= 65535 and within_fraction else scan
                total += statistics.median(row['cpu_ns'] if row.get('cpu_ns') is not None else
                                           row['cpu_user_ns']+row['cpu_sys_ns'] for row in chosen)
            costs.append({'max_partitions': maximum, 'max_fraction': fraction,
                          'training_sum_median_cpu_ns': total})
    winner = min(costs, key=lambda row: (row['training_sum_median_cpu_ns'], row['max_partitions'], row['max_fraction']))
    identities = sorted((row['config_id'], row['paired_round_id'], row.get('raw_path'), row['cpu_ns']) for row in training)
    result = {'status': 'frozen', 'policy': winner, 'candidates': costs,
              'selection': 'minimum sum training cohort median BinHeap/Scan CPU; ties lowest K then rho',
              'training_seed': 20191230, 'evaluation_seed': 20191231,
              'training_identity_sha256': hashlib.sha256(json.dumps(identities).encode()).hexdigest(),
              'training_rows': len(training), 'evaluation_rows_used': 0,
              'scope': 'Finite predeclared training grid; no optimal-policy or held-out performance claim.'}
    output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    return result
