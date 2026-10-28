"""Single Google Benchmark raw-to-row normalization boundary for P6."""
from __future__ import annotations
import json
from pathlib import Path
import re

_UNITS = {'ns': 1, 'us': 1000, 'ms': 1000000, 's': 1000000000}


def normalize_gbench(raw_json: str | Path | dict, common_metadata: dict) -> list[dict]:
    """Keep individual repetitions/errors; aggregates cannot replace observations.

    Random interleaving does not make GBench repetition indices paired process
    rounds. Micro ratios use the explicitly independent-interleaved design.
    ``common_metadata`` carries actual source/environment/input/audit references.
    """
    if isinstance(raw_json, (str, Path)):
        path = Path(raw_json)
        document = json.loads(path.read_text())
        raw_path = str(path)
    else:
        document, raw_path = raw_json, common_metadata.get('raw_path')
    result = []
    for raw in document.get('benchmarks', []):
        if raw.get('run_type') == 'aggregate':
            continue
        name = raw.get('run_name', raw.get('name', 'unknown'))
        parts = name.split('/')
        experiment = 'M3' if parts[0].startswith('M3-') else parts[0]
        config = dict(common_metadata.get('config', {}))
        config.update(profile=name, mode='microbenchmark',
                      cache_treatment=document.get('context', {}).get('tiplog_cache_treatment',
                                                                     'micro-loop-natural'))
        label = raw.get('label')
        if label:
            try: config.update(json.loads(label))
            except json.JSONDecodeError: config['raw_label'] = label
        arm = parts[-1]
        config['kernel'] = arm
        if experiment.startswith('M1'):
            match = re.search(r'/k(\d+)/([^/]+)/N(\d+)/', '/' + name)
            if match:
                config.update(k=int(match[1]), pattern=match[2], outputs=int(match[3]))
                if match[2].startswith('geometric'):
                    config['run_length'] = int(match[2][9:])
                if match[2].startswith('zipf'):
                    config['zipf'] = float(match[2][4:])
            denominator = raw.get('outputs_per_iteration', config.get('outputs'))
        elif experiment == 'M2':
            match = re.search(r'payload_([^/]+)/P(\d+)/([^/]+)/B(\d+)', name)
            if match:
                config.update(payload=match[1], P=int(match[2]), distribution=match[3],
                              B=int(match[4]), index_enabled=arm == 'index_on')
            denominator = raw.get('publishes_per_iteration')
        elif experiment == 'M3':
            config['operation'] = parts[0].removeprefix('M3-')
            match = re.search(r'/B(\d+)', name)
            if match: config['B'] = int(match[1])
            denominator = raw.get('operations_per_iteration')
        else:
            denominator = raw.get('items_per_iteration', raw.get('entries_per_iteration', 1))
        scale = _UNITS.get(raw.get('time_unit', 'ns'))
        if scale is None:
            raise ValueError('unknown Google Benchmark time unit')
        failed = bool(raw.get('error_occurred'))
        status = 'crash' if failed else 'ok'
        cpu = raw.get('cpu_time')
        wall = raw.get('real_time')
        cpu_ns = float(cpu)*scale if cpu is not None else None
        wall_ns = float(wall)*scale if wall is not None else None
        item_cpu = cpu_ns/denominator if cpu_ns is not None and denominator else None
        item_wall = wall_ns/denominator if wall_ns is not None and denominator else None
        row = dict(common_metadata)
        row.update(exp=experiment, config_id=name, comparison_id='/'.join(parts[:-1]),
                   rep=raw.get('repetition_index'), round_id=None, paired_round_id=None,
                   design='independent-interleaved-micro-repetitions', warmup=False,
                   config=config, status=status, wall_ns=wall_ns, cpu_ns=cpu_ns,
                   item_cpu_ns=item_cpu, item_wall_ns=item_wall,
                   cpu_user_ns=None, cpu_sys_ns=None, counters=None,
                   work={key: value for key, value in raw.items() if isinstance(value, (int, float))},
                   out_count=denominator, out_digest=config.get('expected_hash_hex'),
                   oracle_digest=config.get('expected_hash_hex'), raw_path=raw_path,
                   gbench_context=document.get('context', {}),
                   gbench_iterations=raw.get('iterations'),
                   gbench_repetitions=raw.get('repetitions'),
                   error=raw.get('error_message'), raw_gbench=raw)
        if experiment == 'M3':
            if config['operation'] == 'seek': row['seek_ns'] = item_cpu
            elif config['operation'] == 'scan': row['scan_ns_per_entry'] = item_cpu
        result.append(row)
    return result
