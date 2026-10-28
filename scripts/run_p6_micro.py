#!/usr/bin/env python3
"""Run resumable, isolated P6 microbenchmark blocks using the pinned protocol.

Default prints the complete plan. A run needs an actual quiescence record.
Raw attempts and individual observations are preserved, including failures.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import statistics
import sys

import run_p5_pilot as protocol
from check_p5_pilot import sequence_digest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'py'))
from tiplog_py.exp.normalize import normalize_gbench

COUNTS = (1, 2, 4, 8, 16, 64, 256, 1024, 4096, 16384)

_original_process_scan = protocol.proc_scan


def process_scan() -> dict:
    """Include new P6/P7 executable names in the inherited visible-PID check."""
    result = _original_process_scan()
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            words = [part.decode(errors='replace') for part in path.read_bytes().split(b'\0') if part]
        except (OSError, ProcessLookupError):
            continue
        if not words:
            continue
        name = Path(words[0]).name
        if name in {'tiplog_bench', 'index_bench', 'tiplog_layout'} or (
                name.startswith('python') and 'tiplog_py.exp.run' in words):
            result['offenders'].append({'pid': int(path.parent.name), 'argv': words})
    return result


protocol.proc_scan = process_scan


def plan(kind: str, seed: int) -> list[dict]:
    if kind == 'pilot-M1':
        return [{'label': 'pilot-M1-uniform64-BinHeap', 'cases': 1,
                 'kind': 'M1', 'argv': [str(ROOT / 'build/release/merge_bench'),
                 '--profile=uniform64', f'--seed={seed}',
                 '--benchmark_filter=^M1/k64/uniform/N4194304/BinHeap$']}]
    if kind == 'M1':
        return [{'label': f'{prefix}-k{k}', 'cases': 45, 'kind': 'M1',
                 'argv': [str(ROOT / 'build/release/merge_bench'), '--profile=full',
                          '--quad-padding-both', f'--seed={seed}',
                          f'--benchmark_filter=^{prefix}/k{k}/']}
                for prefix in ('M1', 'M1-touch') for k in COUNTS]
    if kind == 'M2':
        return [{'label': f'M2-P{partitions}-B{entries}', 'cases': 20, 'kind': 'M2',
                 'argv': [str(ROOT / 'build/release/publish_bench'), '--matrix',
                          '--seed', str(seed),
                          f'--benchmark_filter=^M2/payload_[^/]+/P{partitions}/[^/]+/B{entries}/']}
                for partitions in (1, 100, 10000) for entries in (256, 1024)]
    if kind == 'M3':
        return [{'label': 'M3-real-partition-sizes', 'cases': 8, 'kind': 'M3',
                 'argv': [str(ROOT / 'build/release/index_bench'), '--trace',
                          'data/traces/itch_20191230_0930_1000_spec.mdt']}]
    raise ValueError(kind)


def expected_names(block: dict) -> set[str]:
    """Require the declared matrix, beyond a coincidentally equal case count."""
    label = block['label']
    if block['kind'] == 'M3':
        return {f'M3-{operation}/B{entries}' for operation in ('seek', 'scan')
                for entries in (64, 256, 1024, 4096)}
    if block['kind'] == 'M1':
        if label.startswith('pilot-'):
            return {'M1/k64/uniform/N4194304/BinHeap'}
        prefix, count = label.rsplit('-k', 1)
        return {f'{prefix}/k{count}/{pattern}/N4194304/{kernel}'
                for pattern in ('uniform', 'geometric1', 'geometric4', 'geometric16',
                                'geometric64', 'geometric256', 'zipf0', 'zipf0.8', 'zipf1.1')
                for kernel in ('StdPQ', 'BinHeap', 'Quad-pad3', 'Loser', 'Quad-pad0')}
    match = re.fullmatch(r'M2-P(\d+)-B(\d+)', label)
    if not match:
        raise ValueError('unknown M2 matrix block: ' + label)
    partitions, entries = match.groups()
    return {f'M2/payload_{payload}/P{partitions}/{distribution}/B{entries}/index_{enabled}'
            for payload in ('empirical', '12', '32', '64', '256')
            for distribution in ('uniform', 'zipf1.1') for enabled in ('on', 'off')}


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify_block(directory: Path, block: dict, repetitions: int) -> dict:
    """Check each invocation; bulk GBench rows do not identify calibration."""
    errors, checks = [], 0
    def check(condition, label):
        nonlocal checks
        checks += 1
        if not condition:
            errors.append(label)
    raw = json.loads((directory / 'gbench.json').read_text())
    rows = [row for row in raw['benchmarks'] if row.get('run_type') != 'aggregate']
    grouped = defaultdict(list)
    for row in rows:
        name = row.get('run_name', row['name'])
        grouped[name].append(row)
        check(not row.get('error_occurred') and not row.get('skipped'), f'non-ok:{name}')
        check(row.get('time_unit') == 'ns', f'unit:{name}')
    check(len(grouped) == block['cases'], 'case-count')
    check(set(grouped) == expected_names(block), 'declared-case-universe')
    invocations = lines(directory / 'invocations.jsonl')
    check(bool(invocations), 'nonempty-invocations')
    check([row['invocation'] for row in invocations] == list(range(len(invocations))),
          'ordered-invocations')
    for name, group in grouped.items():
        check(sorted(row.get('repetition_index', -1) for row in group) == list(range(repetitions)),
              f'repetitions:{name}')
        required = Counter(row.get('iterations') for row in group)
        seen = Counter(row['iterations'] for row in invocations if row['profile'] == name)
        check(all(seen[key] >= count for key, count in required.items()), f'invocation-coverage:{name}')
    for row in invocations:
        check(row['cpu_start'] == row['cpu_end'] == 2 and not row['failed'],
              f'cpu/outcome:{row["invocation"]}')
        check(row['iterations'] > 0, f'positive-iterations:{row["invocation"]}')
        check(row['seed'] == block['seed'], f'input-seed:{row["invocation"]}')
        check(row['cpu2_frequency_start_khz'] is not None and row['cpu2_frequency_end_khz'] is not None,
              f'frequency:{row["invocation"]}')
    if block['kind'] == 'M1':
        inputs = lines(directory / 'inputs.jsonl')
        check(len(inputs) == len(invocations), 'input-manifest-count')
        identities = {}
        for item, invocation in zip(inputs, invocations):
            name = item['profile'] + '/' + item['kernel']
            check(name == invocation['profile'], f'input-profile:{name}')
            check(item['outputs'] == (1 << 22) and not item['diagnostic'], f'full-input:{name}')
            check(invocation['outputs_per_iteration'] == (1 << 22) and
                  int(invocation['digest_hex'], 16) == int(item['expected_hash_hex'], 16),
                  f'independent-sorted-union-digest:{name}')
            identity = (item['input_hash_hex'], item['expected_hash_hex'])
            previous = identities.setdefault(item['profile'], identity)
            check(previous == identity, f'identical-kernel-input:{name}')
            if name.startswith('M1-touch/'):
                check(item['touch_initialized_bytes'] == (1 << 30) and
                      item['touch_loaded_bytes'] == (1 << 22) * 8,
                      f'full-touch:{name}')
    elif block['kind'] == 'M2':
        for invocation in invocations:
            details = invocation['details']
            count = invocation['iterations'] * invocation['outputs_per_iteration']
            start = details['start_head_seq']
            check(details['end_head_seq'] - start == count and
                  int(invocation['digest_hex'], 16) == sequence_digest(start, count),
                  f'independent-sequence-prefix:{invocation["invocation"]}')
            check(details['prefill_data_evicted'] > 0 and
                  details['prefill_pressure_data_evicted'] == details['end_pressure_data_evicted'] == 0,
                  f'prefill/pressure:{invocation["invocation"]}')
    else:
        inputs = lines(directory / 'inputs.jsonl')
        check(len(inputs) == len(invocations), 'M3-input-manifest-count')
        identities = set()
        for item, invocation in zip(inputs, invocations):
            name = invocation['profile']
            check(item['profile'] == name, f'M3-input-profile:{name}')
            check(int(invocation['digest_hex'], 16) == int(item['expected_hash_hex'], 16),
                  f'M3-independent-position-vector-digest:{name}')
            check(invocation['outputs_per_iteration'] == item['operations_per_iteration'],
                  f'M3-operation-count:{name}')
            check(item['input_records'] == 32817244 and not item.get('diagnostic', True),
                  f'M3-full-real-window:{name}')
            check(item['block_entries'] == int(name.rsplit('/B', 1)[1]), f'M3-block-size:{name}')
            check(item['seek_queries'] == 4096, f'M3-query-count:{name}')
            identities.add(tuple(item[key] for key in ('input_hash_hex', 'query_hash_hex',
                           'logical_head', 'trace_file_bytes', 'input_records', 'trace_path')))
        check(len(identities) == 1, 'M3-identical-input-and-query-schedule')
    return {'status': 'passed' if not errors else 'failed', 'checks': checks, 'errors': errors,
            'individual_rows': len(rows), 'invocations': len(invocations),
            'raw_json': protocol.identity(directory / 'gbench.json'),
            'limits': 'All invocations checked; exact warm-up/calibration-to-bulk-row mapping is unexposed. No hardware or constant-clock claim.'}


def frequency_flags(state: dict, destination: Path) -> dict:
    samples, unreadable = [], []
    for block in state['blocks']:
        path = ROOT / block['directory']
        command = block.get('command', {})
        for point in ('before', 'after'):
            value = command.get(point, {}).get('cpu2_frequency_khz')
            if value is not None:
                samples.append({'block': block['label'], 'attempt': block['attempt'],
                                'invocation': None, 'boundary': point, 'frequency_khz': value})
        if (path / 'invocations.jsonl').exists():
            try:
                invocations = lines(path / 'invocations.jsonl')
            except (OSError, ValueError) as error:
                unreadable.append({'path': str(path / 'invocations.jsonl'), 'error': str(error)})
                continue
            for row in invocations:
                for point in ('start', 'end'):
                    value = row.get(f'cpu2_frequency_{point}_khz')
                    if value is not None:
                        samples.append({'block': block['label'], 'attempt': block['attempt'],
                                        'invocation': row['invocation'], 'boundary': point,
                                        'frequency_khz': value})
    median = statistics.median(row['frequency_khz'] for row in samples) if samples else None
    for row in samples:
        row['flagged_over_10_percent'] = abs(row['frequency_khz'] / median - 1) > .10
    result = {'session_median_khz': median, 'samples': samples, 'unreadable_invocation_logs': unreadable,
              'flagged_samples': sum(row['flagged_over_10_percent'] for row in samples),
              'policy': 'All flagged endpoints/invocations/rows retained. Endpoints include setup and do not prove constant hot-loop clocks.'}
    protocol.save(destination, result)
    return {'path': str(destination.relative_to(ROOT)), 'session_median_khz': median,
            'flagged_samples': result['flagged_samples'], 'total_samples': len(samples)}


def append_observations(destination: Path, new_rows: list[dict]) -> None:
    def key(row):
        return (row['run_id'], row['block'], row['attempt'], row['config_id'], row.get('rep'))
    existing = {key(row) for row in lines(destination)} if destination.exists() else set()
    with destination.open('a') as stream:
        for row in new_rows:
            if key(row) not in existing:
                stream.write(json.dumps(row) + '\n')
                existing.add(key(row))
        stream.flush()
        os.fsync(stream.fileno())


def failed_process_row(state, block, attempt, block_dir, repetitions, reason):
    return {
        'run_id': state['run_id'], 'block': block['label'], 'attempt': attempt,
        'exp': block['kind'], 'config_id': block['label'] + '/process-failure',
        'rep': None, 'warmup': False, 'status': 'crash', 'error': reason,
        'oracle_validated': False, 'cpu_ns': None, 'wall_ns': None,
        'config': {'profile': block['label'], 'mode': 'microbenchmark'},
        'measurement_scope': 'Failed process/output attempt; case-level observations unavailable',
        'requested_cases': block['cases'], 'requested_repetitions': repetitions,
        'command_reference': str((block_dir / 'command.json').relative_to(ROOT)),
        'raw_path': str((block_dir / 'stderr.log').relative_to(ROOT)),
        'git': state['provenance']['git'], 'seed': block['seed'], 'preset': 'release',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('M1', 'M2', 'M3', 'pilot-M1'), required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--quiescence-record', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--repetitions', type=int, default=15)
    parser.add_argument('--seed', type=int, default=20191230)
    args = parser.parse_args()
    minimum = 30 if args.kind == 'pilot-M1' else 15
    if args.repetitions < minimum:
        parser.error(f'at least{minimum} repetitions required')
    blocks = plan(args.kind, args.seed)
    for block in blocks:
        block['seed'] = args.seed
    flags = [flag for flag in protocol.FLAGS if not flag.startswith('--benchmark_repetitions=')]
    flags.insert(0, f'--benchmark_repetitions={args.repetitions}')
    configuration = {'kind': args.kind, 'blocks': blocks, 'flags': flags,
                     'seed': args.seed, 'repetitions': args.repetitions}
    if not args.run:
        print(json.dumps({'status': 'plan-only', **configuration,
                          'total_cases': sum(block['cases'] for block in blocks)}, indent=2))
        return 0
    if args.quiescence_record is None:
        parser.error('--run requires saved quiescence record')
    declaration = args.quiescence_record.resolve()
    lock_path = ROOT / 'build/p6/micro.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    affinity = [cpu for cpu in os.sched_getaffinity(0) if cpu not in (2, 3)]
    if not affinity:
        raise RuntimeError('observer requires CPU outside2/3')
    os.sched_setaffinity(0, affinity)
    protocol.FLAGS = flags
    if args.resume:
        state = json.loads(args.resume.read_text())
        if state['configuration'] != configuration:
            raise RuntimeError('resume configuration differs')
        directory = ROOT / state['output_directory']
        for item in state['provenance']['source_files'] + state['provenance']['binaries']:
            if protocol.sha(ROOT / item['path']) != item['sha256']:
                raise RuntimeError('source/binary changed since campaign: ' + item['path'])
    else:
        revision = protocol.git_info()
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        run_id = f"{stamp}_{revision['sha'][:12]}{'-dirty' if revision['dirty'] else ''}_{platform.node()}"
        directory = ROOT / 'results/raw/P6' / args.kind / run_id
        directory.mkdir(parents=True, exist_ok=False)
        state = {'status': 'preflight', 'run_id': run_id, 'started_utc': protocol.now(),
                 'configuration': configuration, 'output_directory': str(directory.relative_to(ROOT)),
                 'blocks': [], 'machine_settings_changed': False, 'command': sys.argv}
    latest = ROOT / f'results/p6/micro-{args.kind}-latest.json'
    latest.parent.mkdir(parents=True, exist_ok=True)
    def checkpoint():
        protocol.save(directory / 'session.json', state)
        protocol.save(latest, state)
    checkpoint()
    try:
        state['quiescence'] = protocol.require_quiet(declaration)
        if not args.resume:
            provenance = protocol.provenance()
            provenance['binaries'].append(protocol.identity(ROOT / 'build/release/index_bench'))
            provenance['input_scope'] = ('Full accepted ITCH window partition sizes' if args.kind == 'M3'
                                         else 'Deterministic synthetic micro workloads')
            for parent in (ROOT / 'py/tiplog_py', ROOT / 'configs'):
                provenance['source_files'].extend(protocol.identity(path) for path in sorted(parent.rglob('*'))
                    if path.is_file() and '__pycache__' not in path.parts)
            state['provenance'] = provenance
            protocol.save(directory / 'provenance.json', provenance)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        capture = protocol.command_record([str(ROOT / 'scripts/env_capture.sh'), '--cpu', '2', '--preset', 'release'],
                    directory / f'environment-{stamp}.json', directory / f'environment-{stamp}.stderr.log')
        state.setdefault('captures', []).append(capture)
        if capture['returncode']:
            raise RuntimeError('environment capture failed')
        environment_path = ROOT / capture['stdout']['path']
        environment = json.loads(environment_path.read_text())
        if not (environment['controls']['ac_online'] is True and environment['affinity']['pin_verified']
                and environment['affinity']['cpu_is_core_pmu_member']):
            raise RuntimeError('mandatory AC/CPU2/P-core checks failed')
        disable_aslr = environment['controls']['per_process_aslr_probe']['returncode'] == 0
        state['status'] = 'running'
        checkpoint()
        for block in blocks:
            attempts = [old for old in state['blocks'] if old['label'] == block['label']]
            if any(old['status'] == 'passed' for old in attempts):
                continue
            if attempts and attempts[-1]['status'] == 'running':
                attempts[-1].update(status='interrupted', reason='No terminal child/normalization checkpoint; preserved as unconfirmed')
            attempt = len(attempts) + 1
            block_dir = directory / f"{block['label']}-attempt{attempt:03}"
            block_dir.mkdir(exist_ok=False)
            row = {**block, 'attempt': attempt, 'status': 'running',
                   'directory': str(block_dir.relative_to(ROOT))}
            state['blocks'].append(row)
            checkpoint()
            row['command'] = protocol.run_block(block_dir, block['argv'], disable_aslr, declaration)
            if (block_dir / 'gbench.json').exists():
                compile_commands = json.loads((ROOT / 'build/release/compile_commands.json').read_text())
                filename = {'M1': 'merge_bench.cpp', 'M2': 'publish_bench.cpp',
                            'M3': 'index_bench.cpp'}[block['kind']]
                compile_command = next(item['command'] for item in compile_commands if Path(item['file']).name == filename)
                common = {'run_id': state['run_id'], 'block': block['label'], 'attempt': attempt,
                          'seed': args.seed, 'cpu': 2, 'preset': 'release',
                          'git': {key:value for key,value in state['provenance']['git'].items()
                                  if key != 'status_porcelain'},
                          'environment_reference': str(environment_path.relative_to(ROOT)),
                          'provenance_reference': str((directory / 'provenance.json').relative_to(ROOT)),
                          'command_reference': str((block_dir / 'command.json').relative_to(ROOT)),
                          'flags': compile_command, 'benchmark_flags': flags,
                          'compiler': environment['tools']['g++'],
                          'input_sha256': {item['path']: item['sha256'] for item in state['provenance']['inputs']},
                          'input_kind': state['provenance']['input_scope'],
                          'freq_before': row['command']['before']['cpu2_frequency_khz'],
                          'freq_after': row['command']['after']['cpu2_frequency_khz'],
                          'frequency_observation_reference': str((block_dir / 'invocations.jsonl').relative_to(ROOT)),
                          'frequency_flags_reference': str((directory / 'frequency-flags.json').relative_to(ROOT)),
                          'measurement_command_ok': row['command']['status'] == 'ok'}
                normalized = []
                try:
                    normalized = normalize_gbench(block_dir / 'gbench.json', common)
                    row['audit'] = verify_block(block_dir, block, args.repetitions)
                except Exception as exc:
                    row['audit'] = {'status': 'failed', 'errors': [f'{type(exc).__name__}: {exc}']}
                try:
                    observed = lines(block_dir / 'invocations.jsonl') if (block_dir / 'invocations.jsonl').exists() else []
                except (OSError, ValueError) as error:
                    observed = []
                    row['audit'].update(status='failed')
                    row['audit']['errors'].append('unusable invocation log: ' + str(error))
                protocol.save(block_dir / 'audit.json', row['audit'])
                for observation in normalized:
                    observation['oracle_validated'] = row['audit']['status'] == 'passed'
                    observation['validation_reference'] = str((block_dir / 'audit.json').relative_to(ROOT))
                    if not observation['oracle_validated']:
                        observation['raw_status'] = observation['status']
                        observation['status'] = 'oracle_mismatch'
                    if block['kind'] == 'M2':
                        candidates = [item for item in observed if item['profile'] == observation['config_id']
                                      and item['iterations'] == observation['gbench_iterations']]
                        actuals = {item['digest_hex'] for item in candidates}
                        starts = {item['details']['start_head_seq'] for item in candidates}
                        if len(actuals) == len(starts) == 1:
                            count = observation['gbench_iterations'] * candidates[0]['outputs_per_iteration']
                            observation['out_count'] = count
                            observation['out_digest'] = next(iter(actuals))
                            observation['oracle_digest'] = f'{sequence_digest(next(iter(starts)), count):x}'
                        else:
                            observation['out_digest'] = observation['oracle_digest'] = None
                            observation['digest_mapping_limit'] = 'No unique digest for measured iteration count; all individual invocation digests remain independently audited'
                if not normalized:
                    normalized = [failed_process_row(state, block, attempt, block_dir,
                                                     args.repetitions, row['audit'].get('errors'))]
                append_observations(directory / 'runs.jsonl', normalized)
            else:
                row['audit'] = {'status': 'failed', 'errors': ['missing Google Benchmark output']}
                append_observations(directory / 'runs.jsonl', [failed_process_row(
                    state, block, attempt, block_dir, args.repetitions, 'missing Google Benchmark output')])
            row['status'] = 'passed' if row['command']['status'] == 'ok' and row['audit']['status'] == 'passed' else 'failed'
            state['frequency_flags'] = frequency_flags(state, directory / 'frequency-flags.json')
            checkpoint()
            if row['status'] != 'passed':
                raise RuntimeError('micro block failed; retained raw attempt: ' + block['label'])
        frozen = state['provenance']['source_files'] + state['provenance']['binaries']
        state['source_binary_changes'] = [item['path'] for item in frozen
                                         if protocol.sha(ROOT / item['path']) != item['sha256']]
        if state['source_binary_changes']:
            raise RuntimeError('source/binary changed during campaign')
        state['quiescence_after'] = protocol.require_quiet(declaration)
        state['status'] = 'passed'
    except BaseException as exc:
        state.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    state['finished_utc'] = protocol.now()
    checkpoint()
    print(json.dumps({'status': state['status'], 'session': str(directory / 'session.json'),
                      'error': state.get('error')}), flush=True)
    return 0 if state['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
