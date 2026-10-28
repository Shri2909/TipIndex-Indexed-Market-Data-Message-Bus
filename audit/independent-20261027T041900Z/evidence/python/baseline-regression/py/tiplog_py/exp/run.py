"""Prepare and execute process-level paired P6 experiments.

Preparation/oracle work is separate from measurement execution. The runner never
compiles, converts, studies sources, or fuzzes during a measurement block.
"""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import numpy as np
from . import matrix
from .hashes import build_accelerator, sha_file
from .oracle import TraceIndex, OutcomeOracle, digest_selection, validate
from .synthetic import empirical_mix, schedule, schedule_summary

ROOT = Path(__file__).resolve().parents[3]
T2_GROUP_IDENTITY_VERSION = 2


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()

def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix+'.partial')
    if path.suffix == '.gz':
        with gzip.open(partial, 'wt') as stream: json.dump(value, stream, sort_keys=True)
    else: partial.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')
    partial.replace(path)


def read_json(path):
    if str(path).endswith('.gz'):
        with gzip.open(path, 'rt') as stream: return json.load(stream)
    return json.loads(Path(path).read_text())


def append(path: Path, rows):
    """O_APPEND and fsync retain failed attempts without replacing earlier rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        for row in rows: stream.write(json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n')
        stream.flush(); os.fsync(stream.fileno())


def row_identity(row):
    return (row.get('process_round_id', row.get('process_id')), row.get('config_id'))


def _row_bytes(row):
    return (json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')


def _collection_identities(path, rows, *, marker, payload, filename):
    """Stream committed records; repair only a journal-owned incomplete tail."""
    observed = set()
    expected = {row_identity(row): row for row in rows}
    if len(expected) != len(rows):
        raise ValueError('pending journal contains duplicate row identities')
    boundary = payload.get('collection_offsets', {}).get(filename)
    initial_size = boundary if boundary is not None else 0
    if (path.stat().st_size if path.exists() else 0) < initial_size:
        raise ValueError(f'{path}: committed prefix is shorter than the pending journal boundary')
    if not path.exists():
        return observed
    # Legacy markers have no byte boundary: recognize only a contiguous exact
    # journal prefix, and require all subsequent rows to continue that sequence.
    # Earlier complete rows remain untouched; an ambiguous tail is never dropped.
    pending_index = 0
    publication_started = False
    with path.open('r+b') as stream:
        number = 0
        while True:
            offset = stream.tell()
            raw = stream.readline()
            if not raw:
                break
            number += 1
            if boundary is not None and offset < boundary < stream.tell():
                raise ValueError(f'{path}:{number}: pending journal boundary is inside a committed row')
            try:
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise ValueError('JSONL row must be an object')
            except (ValueError, UnicodeDecodeError) as exc:
                # A malformed newline-terminated row, or any following bytes,
                # is corruption inside the file and must never be discarded.
                pending = rows[pending_index] if pending_index < len(rows) else None
                start = boundary
                authorized = (not raw.endswith(b'\n') and not stream.read(1) and pending is not None
                              and (start is None or offset >= start)
                              and _row_bytes(pending).startswith(raw))
                if not authorized:
                    raise ValueError(f'{path}:{number}: corrupt committed JSONL row') from exc
                fd, evidence = tempfile.mkstemp(prefix=marker.name+'.', suffix='.torn-tail.bin', dir=marker.parent)
                with os.fdopen(fd, 'wb') as saved:
                    saved.write(raw); saved.flush(); os.fsync(saved.fileno())
                payload.setdefault('recovered_tails', []).append({
                    'collection': filename, 'offset': offset, 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'preserved_path': evidence})
                # Publish the evidence reference before modifying the append file.
                save(marker, payload)
                stream.truncate(offset); stream.flush(); os.fsync(stream.fileno())
                break
            identity = row_identity(row)
            if identity in observed:
                raise ValueError(f'{path}:{number}: duplicate committed row identity')
            owned = ((boundary is not None and offset >= boundary) or publication_started or identity in expected)
            if owned:
                if boundary is not None and offset < boundary:
                    raise ValueError(f'{path}:{number}: pending journal row precedes its saved boundary')
                if pending_index >= len(rows) or row != rows[pending_index]:
                    raise ValueError(f'{path}:{number}: row differs from authoritative pending journal sequence')
                publication_started = True
                pending_index += 1
            observed.add(identity)
            if not raw.endswith(b'\n'):
                if identity not in expected:
                    raise ValueError(f'{path}:{number}: unowned unterminated JSONL row')
                stream.write(b'\n'); stream.flush(); os.fsync(stream.fileno())
                break
    return observed


def publish_commit(directory: Path, marker: Path, payload: dict, state: dict, identities: dict):
    """Finish a saved process journal once; preserve and repair its torn tail.

    Existing committed interior corruption is rejected. A malformed final record
    is recoverable only if its bytes match the next authoritative pending row.
    """
    if payload.get('status') == 'committed': return
    for filename, rows in payload['collections'].items():
        path = directory/filename
        if Path(filename).name != filename:
            raise ValueError('journal collection must be a local filename')
        # Scan after every interruption, including retries in the same process.
        if filename not in identities:
            identities[filename] = _collection_identities(path, rows, marker=marker,
                payload=payload, filename=filename)
        fresh = [row for row in rows if row_identity(row) not in identities[filename]]
        try:
            append(path, fresh)
        except BaseException:
            identities.pop(filename, None)
            raise
        identities[filename].update(row_identity(row) for row in fresh)
    completed = payload['completion']
    if not any(item['id'] == completed['id'] for item in state['completed_processes']):
        state['completed_processes'].append(completed)
    save(directory/'state.json', state)
    save(marker, {'status':'committed', 'completion':completed,
                  'recovered_tails':payload.get('recovered_tails', []),
                  'published_counts':{name:len(rows) for name,rows in payload['collections'].items()}})


def require_frozen(provenance):
    for item in provenance['source_files'] + provenance['binaries']:
        if sha_file(ROOT/item['path']) != item['sha256']:
            raise ValueError('measurement source/binary changed: '+item['path'])


def digest_requests(workload, oracle):
    expected = {}
    for row in workload['requests']:
        if row.get('checkpoint_at_snapshot_head'):
            # T5 observes an immutable memory snapshot, rather than replaying
            # unavailable history. Capture its head independently from input.
            row['after_seq'] = len(oracle.rows)
        elif 'after_seq' not in row:
            row['after_seq'] = oracle.after_timestamp(row['anchor_ts']-row['backlog_seconds']*10**9)
        expected[row['id']] = oracle.expected(row['after_seq'], row['terms'], mode=row['mode'])
    return expected


def prepare(config_path: Path, directory: Path, *, suite='evaluation') -> dict:
    config = matrix.load(config_path)
    directory.mkdir(parents=True, exist_ok=True)
    accelerator = build_accelerator()
    plan = matrix.make_plan(config, training=suite == 'training', pilot=suite == 'pilot')
    index = None
    if suite != 'training': index = TraceIndex(config['trace'], ROOT/config['cache_directory'])
    workloads = []
    real_oracles = {}
    prefill_digests = {}
    try:
        for number, workload in enumerate(plan):
            print(json.dumps({'preparing': workload['id'], 'index': number, 'total': len(plan)}), flush=True)
            if workload['kind'] == 'trace':
                oracle_key = (workload['ring_bytes'], workload['anchor_ts'])
                if oracle_key not in real_oracles:
                    real_oracles[oracle_key] = OutcomeOracle(index, workload['ring_bytes'], anchor_ts=workload['anchor_ts'])
                oracle = real_oracles[oracle_key]
            else:
                data, rows, topics = schedule(records=workload['records'], partitions=workload['partitions'],
                                             zipf=workload['zipf'], run_length=workload['run_length'],
                                             seed=workload['seed'], mix=empirical_mix(Path(config['payload_mix'])))
                synthetic_id = hashlib.sha256(rows.tobytes()+data).hexdigest()
                source = SimpleNamespace(data=data, rows=rows, topics=topics, trace_sha256=synthetic_id)
                oracle = OutcomeOracle(source, workload['ring_bytes'])
                workload['synthetic_schedule_sha256'] = synthetic_id
                workload['synthetic_summary'] = schedule_summary(rows, workload['partitions'])
            expected = digest_requests(workload, oracle)
            prefill_key = (oracle.source.trace_sha256, len(oracle.rows))
            if prefill_key not in prefill_digests:
                prefill_digests[prefill_key] = digest_selection(
                    oracle.source.data, oracle.rows, np.arange(len(oracle.rows), dtype=np.int64))
            case_path = directory/(workload['id']+'.json.gz')
            save(case_path, {'workload': workload, 'expected': expected,
                             'layout': {key: value for key, value in oracle.layout.items() if key != 'positions'},
                             'prefill_digest': prefill_digests[prefill_key],
                             'source_identity': oracle.source.trace_sha256})
            workloads.append({'id': workload['id'], 'path': str(case_path), 'sha256': sha_file(case_path),
                              'requests': len(workload['requests'])})
            del oracle
            if workload['kind'] == 'synthetic': del source, data, rows, topics
    finally:
        if index: index.close()
    result = {'status': 'prepared', 'suite': suite, 'config': str(config_path),
              't2_group_identity_version': T2_GROUP_IDENTITY_VERSION,
              'config_sha256': sha_file(config_path), 'workloads': workloads,
              'independent_accelerator': accelerator, 'created_utc': now(),
              'matrix_choice': 'T1 C1GiB all backlogs and C2GiB longest; T3 k=1/sqrt(P)/P and local selectivity .01/.1/1'}
    save(directory/'plan.json', result)
    return result


def p5_helpers():
    spec = importlib.util.spec_from_file_location('tiplog_p5_pilot_helpers', ROOT/'scripts/run_p5_pilot.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    original_scan = module.proc_scan
    def process_scan():
        result = original_scan()
        ancestors = set(result['excluded_runner_ancestors'])
        observed = {item['pid'] for item in result['offenders']}
        for path in Path('/proc').glob('[0-9]*/cmdline'):
            pid = int(path.parent.name)
            if pid in ancestors or pid in observed: continue
            try:
                words = [part.decode(errors='replace') for part in path.read_bytes().split(b'\0') if part]
            except (OSError, ProcessLookupError): continue
            if not words: continue
            name = Path(words[0]).name
            if name in {'tiplog_bench','index_bench','tiplog_layout'} or (
                    name.startswith('python') and 'tiplog_py.exp.run' in words):
                result['offenders'].append({'pid':pid,'argv':words})
        return result
    module.proc_scan = process_scan
    return module


def command_for(binary: str, workload: dict, request_path: Path, output: Path, policy: dict | None,
                term_dictionary: Path | None = None):
    command = ['taskset', '-c', '2', binary, '--requests', str(request_path), '--output', str(output),
               '--ring-bytes', str(workload['ring_bytes']), '--block-entries', str(workload['block_entries']),
               '--seed', str(workload['seed'])]
    if workload['kind'] == 'trace':
        command += ['--trace', workload['trace'], '--anchor-ts', str(workload['anchor_ts'])]
    else:
        command += ['--synthetic', '--records', str(workload['records']), '--partitions', str(workload['partitions']),
                    '--zipf', str(workload['zipf']), '--run-length', str(workload['run_length'])]
        if workload.get('payload_mix'): command += ['--mix', workload['payload_mix']]
    if workload.get('memory'): command += ['--memory']
    if workload.get('allocator_replay'): command += ['--allocator-replay']
    if term_dictionary is not None: command += ['--term-dictionary',str(term_dictionary)]
    if policy:
        command += ['--auto-max-partitions', str(policy['max_partitions']),
                    '--auto-max-fraction', str(policy['max_fraction'])]
    return command


def normalize_actual(actual, request, common, expected):
    result = dict(common)
    config = {key: value for key, value in request.items() if key not in ('terms', 'id', 'comparison_id')}
    config.update(subscription=request['name'], terms_sha256=hashlib.sha256(request['terms'].encode()).hexdigest(),
                  cache_treatment=request['cache_treatment'], B=request['block_entries'],
                  C=request['ring_bytes'])
    cpu_user = actual.get('cpu_user_ns', actual.get('user_ns'))
    cpu_sys = actual.get('cpu_sys_ns', actual.get('system_ns'))
    result.update(actual)
    result.update(exp=request['exp'], config_id=request['id'], comparison_id=request['comparison_id'],
                  config=config, arm=request['mode']+'/'+request['kernel'],
                  cpu_user_ns=cpu_user, cpu_sys_ns=cpu_sys,
                  cpu_ns=actual.get('cpu_ns', (cpu_user or 0)+(cpu_sys or 0)),
                  oracle_digest={'seq_sha256': expected['seq_sha256'], 'payload_sha256': expected['payload_sha256'],
                                 'sink64': expected['sink64']},
                  out_digest={'seq_sha256': actual.get('seq_sha256'), 'payload_sha256': actual.get('payload_sha256'),
                              'sink64': actual.get('sink64')}, oracle=validate(actual, expected))
    result['oracle_validated'] = result['oracle']['status'] == 'passed'
    if not result['oracle_validated']:
        result['raw_status'] = result['status']
        result['status'] = 'oracle_mismatch'
    return result


def aggregate_t2(rows: list[dict]) -> list[dict]:
    result = [row for row in rows if row['exp'] != 'T2']
    grouped = {}
    for row in rows:
        if row['exp'] == 'T2':
            cfg = row['config']
            key = (cfg['reader_count'], cfg['mode'], cfg['kernel'], cfg['cache_treatment'])
            grouped.setdefault(key, []).append(row)
    for key, group in grouped.items():
        count, mode, kernel, cache = key
        first = dict(group[0]); cfg = dict(first['config'])
        per_reader = {'reader_index','name','consumer','symbol','terms_sha256','breadth','subscription'}
        shared = {name:value for name,value in cfg.items() if name not in per_reader}
        for row in group:
            if {name:value for name,value in row['config'].items() if name not in per_reader} != shared:
                raise ValueError('T2 readers disagree on duration or workload configuration')
            for name in ('workload_id','trace_sha256','seed','process_round_id','rep','warmup'):
                if row.get(name) != first.get(name):
                    raise ValueError('T2 readers disagree on '+name)
        duration = cfg.get('market_seconds')
        if (isinstance(duration, bool) or not isinstance(duration, (int,float)) or
                not np.isfinite(duration) or duration <= 0 or cfg.get('backlog_seconds') != duration):
            raise ValueError('T2 requires a positive, consistent declared market duration')
        all_indices = sorted(row['config']['reader_index'] for row in group)
        complete = all_indices == list(range(count))
        all_valid = complete and all(row['oracle']['status'] == 'passed' for row in group)
        group_status = ('crash' if not complete else
                        'oracle_mismatch' if not all_valid else
                        next((row['status'] for row in group if row['status'] != 'ok'), 'ok'))
        cfg.update(subscription='W2-seeded-reader-group', readers=count, market_seconds=duration,
                   R=count, mode=mode, kernel=kernel, cache_treatment=cache)
        for name in ('reader_index','name','consumer','symbol','terms_sha256','breadth'):
            cfg.pop(name,None)
        comparison = {'exp': 'T2', 'R': count, 'cache': cache, 'C': cfg['C'], 'B': cfg['B'],
                      'market_seconds':duration, 'backlog_seconds':cfg['backlog_seconds'],
                      'anchor_ts':cfg.get('anchor_ts'), 'workload_id':first.get('workload_id'),
                      'trace_sha256':first.get('trace_sha256'), 'seed':first.get('seed')}
        effective_counts = {effective:sum(row.get('effective_mode','unknown') == effective for row in group)
                            for effective in sorted({row.get('effective_mode','unknown') for row in group})}
        first.update(config=cfg, t2_group_identity_version=T2_GROUP_IDENTITY_VERSION,
                     comparison_id=matrix.stable_id(comparison),
                     config_id=matrix.stable_id(dict(comparison, mode=mode, kernel=kernel)),
                     group_id=f'T2-R{count}', reader_rows=len(group),
                     out_count=sum(row.get('out_count', 0) for row in group),
                     payload_bytes=sum(row.get('payload_bytes',0) for row in group),
                     wall_ns=sum(row.get('wall_ns', 0) for row in group),
                     cpu_user_ns=sum(row['cpu_user_ns'] for row in group) if all(row['cpu_user_ns'] is not None for row in group) else None,
                     cpu_sys_ns=sum(row['cpu_sys_ns'] for row in group) if all(row['cpu_sys_ns'] is not None for row in group) else None,
                     cpu_ns=sum(row['cpu_ns'] for row in group),
                     status=group_status, oracle_validated=all_valid,
                     out_digest=None, oracle_digest=None, seq_sha256=None,
                     payload_sha256=None, sink64=None, checkpoint=None, error=None,
                     group_digest_scope='No single concatenated-stream digest: every ordered reader is independently validated in reader-runs.jsonl',
                     effective_mode=next(iter(effective_counts)) if len(effective_counts) == 1 else 'mixed',
                     effective_mode_counts=effective_counts,
                     selected_partitions=None,estimated_entries=None,estimated_index_fraction=None,
                     reader_validation={'expected_readers':count,'observed_readers':len(group),
                                        'all_validated':all_valid,
                                        'rows_reference':first.get('reader_validation_rows_reference')},
                     reader_status_counts={status: sum(row['status'] == status for row in group)
                                           for status in sorted(set(row['status'] for row in group))},
                     oracle={'status': 'passed' if all_valid else 'failed'})
        first['frequency_samples_khz'] = [row.get(key) for row in group
                                          for key in ('freq_start_khz','freq_end_khz') if row.get(key)]
        work_names = set().union(*(row.get('work',{}) for row in group))
        first['work'] = {name: sum(row.get('work', {}).get(name, 0) for row in group)
                         for name in work_names}
        result.append(first)
    return result


def perform_process(command, output, stdout, stderr, helpers):
    before = helpers.observation()
    start = time.monotonic_ns()
    with stdout.open('w') as out, stderr.open('w') as err:
        child = subprocess.Popen(command, stdout=out, stderr=err, cwd=ROOT)
        pid = child.pid
        observations = [before]
        while child.poll() is None:
            time.sleep(5)
            observations.append(helpers.observation())
            if observations[-1]['power']['ac_online'] is not True:
                child.terminate()
                child.wait()
                break
    record = {'argv': command, 'pid': pid, 'returncode': child.returncode,
              'wall_ns_including_prefill': time.monotonic_ns()-start,
              'before': before, 'after': helpers.observation(), 'observations': observations,
              'output_path': str(output)}
    actuals = [json.loads(line) for line in output.read_text().splitlines()] if output.exists() else []
    return record, actuals


def measurement_command_ok(record):
    if record is None or record['returncode'] != 0: return False
    return all(sample.get('power', {}).get('ac_online') is True
               for sample in [record['before'],record['after'],*record['observations']])


def prefill_row(actuals: list[dict], expected: dict) -> dict:
    prefills = [row for row in actuals if row.get('kind') == 'prefill']
    if len(prefills) != 1:
        raise ValueError('process must emit exactly one saved prefill result')
    actual = prefills[0]
    if actual['publications'] != expected['out_count'] or actual['publish_sink64'] != expected['sink64']:
        raise ValueError('independent whole-input publisher count/sink mismatch')
    return actual


def validate_synthetic_summary(actual: dict, workload: dict):
    if workload['kind'] != 'synthetic':
        return
    for key, expected in workload['synthetic_summary'].items():
        if key in ('records', 'observed_run_mean'):
            continue  # count already checked; JSON formatting can round mean.
        if actual.get(key) != expected:
            raise ValueError(f'independent synthetic {key} mismatch')


def execute(plan_path: Path, directory: Path, quiescence: Path, *, repetitions=None,
            thresholds: Path | None = None, settle_seconds=60, resume=False) -> dict:
    plan = read_json(plan_path); config = matrix.load(plan['config'])
    if sha_file(Path(plan['config'])) != plan['config_sha256']:
        raise ValueError('prepared matrix changed')
    count = repetitions if repetitions is not None else 30 if plan['suite'] == 'pilot' else config['repetitions']
    if plan['suite'] != 'pilot' and count < 10: raise ValueError('at least10 measured process repetitions are mandatory')
    if plan['suite'] == 'pilot' and count < 30: raise ValueError('P6.2 requires30 T1 pilot repetitions')
    if settle_seconds < 60: raise ValueError('measurement block settling must be at least60s')
    if plan['suite'] == 'evaluation' and thresholds is None:
        raise ValueError('held-out evaluation requires frozen Auto thresholds')
    if plan['suite'] == 'evaluation' and not (ROOT/'results/p6/protocol-freeze.json').exists():
        raise ValueError('pilot response and measurement protocol must be frozen before evaluation')
    policy = read_json(thresholds)['policy'] if thresholds else None
    helpers = p5_helpers()
    # Keep this light observer away from the measured P-core and its SMT sibling.
    allowed = os.sched_getaffinity(0)
    ecores = {cpu for cpu in allowed if cpu >= 4}
    observer = min(ecores or (allowed-{2, 3})) if allowed-{2, 3} else None
    if observer is None:
        raise RuntimeError('observer needs an allowed CPU outside2/3')
    os.sched_setaffinity(0, {observer})
    quiet = helpers.require_quiet(quiescence)
    if helpers.power()['ac_online'] is not True: raise RuntimeError('AC power required')
    directory.mkdir(parents=True, exist_ok=resume)
    environment = directory/('environment-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'.json')
    with environment.open('w') as stream:
        subprocess.run([str(ROOT/'scripts/env_capture.sh')], stdout=stream, check=True)
    environment_record = read_json(environment)
    if resume:
        state = read_json(directory/'state.json')
        if state['plan_sha256'] != sha_file(plan_path) or state['repetitions'] != count:
            raise ValueError('resumption requires the identical prepared plan/repetition count')
        if state.get('status') == 'failed':
            raise ValueError('failed measurement sessions are immutable; repair and start a new affected session')
        provenance = read_json(directory/'provenance.json')
        require_frozen(provenance)
    else:
        provenance = helpers.provenance()
        provenance['binaries'].append(helpers.identity(ROOT/config['binary']))
        provenance['source_files'].extend(helpers.identity(path) for path in sorted(Path(__file__).parent.glob('*'))
                                          if path.is_file() and path.suffix in ('.py','.c'))
        provenance['source_files'].append(helpers.identity(Path(plan['config'])))
        provenance['input_scope'] = 'Accepted real trace window or independently specified synthetic schedule; input identities retained'
        save(directory/'provenance.json', provenance)
    compile_commands = read_json(ROOT/'build/release/compile_commands.json')
    actual_compile = next(item['command'] for item in compile_commands
                          if item['file'].endswith('/tools/tiplog_bench/main.cpp'))
    common = {'run_id': directory.name, 'seed': config['seed'], 'preset': 'release',
              'git': {key:value for key,value in provenance['git'].items()
                      if key != 'status_porcelain'}, 'cpu': 2,
              'compiler': environment_record.get('tools', {}).get('g++'),
              'flags': actual_compile, 'environment_path': str(environment),
              'provenance_reference': str(directory/'provenance.json'),
              'input_sha256': {item['path']:item['sha256'] for item in provenance['inputs']},
              'binary_sha256': sha_file(ROOT/config['binary']), 'counters': None,
              'protocol_sha256': sha_file(ROOT/'results/p6/protocol-freeze.json') if (ROOT/'results/p6/protocol-freeze.json').exists() else None,
              'design': 'paired-process-rounds', 'auto_thresholds': policy,
              'quiescence_record': str(quiescence)}
    common['frequency_flags_reference'] = str(directory/'frequency-flags.json')
    common['observer_cpu_affinity'] = sorted(os.sched_getaffinity(0))
    aslr = environment_record['controls']['per_process_aslr_probe']
    command_prefix = ['setarch', platform.machine(), '-R'] if aslr['returncode'] == 0 else []
    common['aslr_regime'] = 'per-process disabled' if command_prefix else 'host ASLR retained after failed per-process probe'
    if not resume:
        state = {'status': 'running', 'plan': str(plan_path), 'plan_sha256': sha_file(plan_path),
                 'repetitions': count, 'excluded_saved_warmups': 1, 'started_utc': now(),
                 'quiescence': quiet, 'common': common, 'completed_processes': []}
    else:
        if state['common']['auto_thresholds'] != policy or state['common']['aslr_regime'] != common['aslr_regime']:
            raise ValueError('resumption requires identical Auto thresholds and actual ASLR regime')
        state.setdefault('resumptions', []).append({'at_utc':now(),'environment_path':str(environment),'quiescence':quiet})
    identities = {}
    for marker in sorted(directory.glob('*/*.commit.json')):
        payload = read_json(marker)
        publish_commit(directory, marker, payload, state, identities)
    if any(item.get('oracle_failures',0) or item.get('measurement_command_ok') is False or item.get('returncode',0)
           for item in state['completed_processes']):
        state.update(status='failed', failure='Recovered process journal contains a failed observation')
        save(directory/'state.json',state)
        raise RuntimeError(state['failure'])
    # Keep only compact frequency observations, rather than copying raw rows.
    frequency_rows = []
    if resume and (directory/'runs.jsonl').exists():
        with (directory/'runs.jsonl').open() as stream:
            for line in stream:
                row = json.loads(line)
                frequency_rows.append({key:row.get(key) for key in
                    ('config_id','process_round_id','rep','warmup','freq_start_khz','freq_end_khz')}
                    | ({'frequency_samples_khz':row['frequency_samples_khz']} if 'frequency_samples_khz' in row else {}))
    save(directory/'state.json', state)
    # One saved warm-up process followed by >=10 separately spawned evaluation
    # processes for EACH workload. Request arm order is shuffled per paired round.
    for workload_description in plan['workloads']:
        case_path = Path(workload_description['path'])
        if sha_file(case_path) != workload_description['sha256']: raise ValueError('prepared case changed')
        case = read_json(case_path); workload = case['workload']
        completed_reps = {item['rep'] for item in state['completed_processes']
                          if item.get('workload_id') == workload['id']}
        if set(range(-1,count)) <= completed_reps:
            continue
        block_path = directory/workload['id']; block_path.mkdir(exist_ok=resume)
        term_dictionary = block_path/'subscription-terms.tsv'
        term_aliases = matrix.write_term_dictionary(term_dictionary,workload['requests'])
        term_dictionary_identity = {'path':str(term_dictionary),'sha256':sha_file(term_dictionary),
                                    'unique_subscriptions':len(term_aliases)}
        save(block_path/'subscription-terms.identity.json',term_dictionary_identity)
        print(json.dumps({'settling_seconds': settle_seconds, 'block': workload['id']}), flush=True)
        time.sleep(settle_seconds)
        for rep in range(-1, count):
            completed = [item for item in state['completed_processes']
                         if item.get('workload_id') == workload['id'] and item.get('rep') == rep]
            if completed:
                if len(completed) != 1: raise ValueError('duplicate completed process round')
                continue
            if helpers.power()['ac_online'] is not True: raise RuntimeError('AC disconnected; preserving completed evidence')
            scan = helpers.proc_scan()
            if scan['offenders']: raise RuntimeError('measurement competitors visible')
            warmup = rep == -1
            base_id = f'{workload["id"]}-warmup' if warmup else f'{workload["id"]}-rep{rep:02}'
            attempt = 0
            while list(block_path.glob(f'{base_id}-attempt{attempt:02}.*')):
                attempt += 1
            process_id = f'{base_id}-attempt{attempt:02}'
            round_seed = config['seed'] + rep + 1
            shuffled = list(workload['requests']); random.Random(round_seed).shuffle(shuffled)
            requests = block_path/(process_id+'.tsv')
            output, stdout, stderr = (block_path/(process_id+suffix) for suffix in ('.jsonl', '.stdout.log', '.stderr.log'))
            matrix.write_requests(requests, shuffled,term_aliases=term_aliases)
            command = command_prefix + command_for(config['binary'], workload, requests, output, policy,term_dictionary)
            has_t2 = any(row['exp'] == 'T2' for row in shuffled)
            off_record, off_actuals = None, None
            # The actual full trace/window is published in both arms. Randomize
            # the ON/OFF process order in each matched round, and retain both.
            off_first = random.Random(round_seed ^ 0x57a9).getrandbits(1) == 1
            def run_off():
                empty = block_path/(process_id+'-index-off.tsv')
                matrix.write_requests(empty, [])
                off_output = block_path/(process_id+'-index-off.jsonl')
                off_command = command_prefix + command_for(config['binary'], workload, empty, off_output, policy)+['--index-enabled', '0']
                observed, values = perform_process(off_command, off_output,
                    block_path/(process_id+'-index-off.stdout.log'),
                    block_path/(process_id+'-index-off.stderr.log'), helpers)
                observed.update(rep=rep, warmup=warmup, process_id=process_id+'-index-off')
                save(block_path/(process_id+'-index-off.command.json'), observed)
                if observed['returncode']:
                    raise RuntimeError('actual-window index-off publisher diagnostic failed')
                prefill_row(values, case['prefill_digest'])
                return observed, values
            if has_t2 and off_first:
                off_record, off_actuals = run_off()
            record, actuals = perform_process(command, output, stdout, stderr, helpers)
            if has_t2 and not off_first:
                off_record, off_actuals = run_off()
            record.update(process_id=process_id, round_seed=round_seed, rep=rep, warmup=warmup,
                          requests_sha256=sha_file(requests), source_identity=case['source_identity'],
                          term_dictionary=term_dictionary_identity,
                          publisher_order='off-on' if has_t2 and off_first else 'on-off' if has_t2 else None)
            save(block_path/(process_id+'.command.json'), record)
            on_prefill = prefill_row(actuals, case['prefill_digest']) if record['returncode'] == 0 else None
            if on_prefill is not None:
                validate_synthetic_summary(on_prefill, workload)
            by_id = {}
            metadata = []
            for actual in actuals:
                if 'id' in actual:
                    if actual['id'] in by_id: raise ValueError('duplicate request output')
                    by_id[actual['id']] = actual
                else: metadata.append(actual)
            rows = []
            for request in shuffled:
                expected = case['expected'][request['id']]
                actual = by_id.get(request['id'], {'status': 'crash', 'out_count': 0})
                row_common = dict(common, seed=workload['seed'], order_seed=config['seed'],
                                  rep=rep, warmup=warmup, round_id=rep,
                                  paired_round_id=f'{directory.name}:{rep}', process_round_id=process_id,
                                  process_pid=record['pid'], raw_path=str(output), trace_sha256=case['source_identity'],
                                  command_record=str(block_path/(process_id+'.command.json')),
                                  round_seed=round_seed, source_kind=workload['kind'],
                                  frequency_observation=record['after'], workload_id=workload['id'],
                                  measurement_command_ok=(measurement_command_ok(record) and
                                      (request['exp'] != 'T2' or measurement_command_ok(off_record))))
                if request['exp'] == 'T2':
                    row_common['reader_validation_rows_reference'] = str(directory/'reader-runs.jsonl')
                rows.append(normalize_actual(actual, request, row_common, expected))
            normalized = aggregate_t2(rows)
            for row in normalized:
                if row['exp'] == 'T2' and on_prefill is not None and off_actuals is not None:
                    off_prefill = prefill_row(off_actuals, case['prefill_digest'])
                    delta = on_prefill['publish_cpu_ns']-off_prefill['publish_cpu_ns']
                    window_seconds = (workload['anchor_ts']-34200000000000)/1e9
                    row['work'].update(publish_index_on_cpu_ns=on_prefill['publish_cpu_ns'],
                        publish_index_off_cpu_ns=off_prefill['publish_cpu_ns'],
                        publish_index_delta_cpu_ns=delta,
                        publish_window_market_seconds=window_seconds,
                        amortized_index_cpu_ns=delta*row['config']['market_seconds']/window_seconds)
                    row['publisher_off_command_record'] = str(block_path/(process_id+'-index-off.command.json'))
                    row.setdefault('frequency_samples_khz',[]).extend(
                        item.get(key) for item in (on_prefill,off_prefill)
                        for key in ('freq_start_khz','freq_end_khz') if item.get(key))
                if row['exp'] == 'T5':
                    memory = next((item for item in metadata if item.get('kind') == 'memory'), None)
                    allocator = next((item for item in metadata if item.get('kind') == 'allocator'), None)
                    row.update(memory=memory.get('memory') if memory else None,
                               gauges=memory.get('gauges') if memory else None,
                               memory_recount=memory, allocator=allocator)
                    if allocator is not None:
                        row['work']['observed_allocator_overhead_bytes'] = allocator['observed_allocator_overhead_bytes']
                    if memory is None or allocator is None or memory.get('recount_equal') is not True or allocator.get('stats_equal') is not True:
                        row.update(raw_status=row['status'], status='oracle_mismatch', oracle_validated=False,
                                   oracle={'status': 'failed', 'reason': 'T5 memory/allocator evidence missing'})
            compact_metadata = [dict({key: value for key, value in item.items() if key != 'owner_counts'},
                                     raw_record_path=str(output)) for item in metadata]
            completion = {'id': process_id, 'workload_id':workload['id'], 'rep':rep,
                          'returncode': record['returncode'], 'rows': len(rows),
                          'measurement_command_ok':all(row['measurement_command_ok'] for row in rows),
                          'oracle_failures': sum(row['oracle']['status'] != 'passed' for row in rows+normalized)}
            payload = {'status':'pending', 'completion':completion, 'collections':{
                'reader-runs.jsonl':[row for row in rows if row['exp'] == 'T2'],
                'runs.jsonl':normalized,
                'process-metadata.jsonl':[{'process_id':process_id, 'warmup':warmup, 'rep':rep,
                    'records':compact_metadata, 'command':record,
                    'publisher_off_command':off_record, 'publisher_off_records':off_actuals}]}}
            payload['collection_offsets'] = {name:(directory/name).stat().st_size
                if (directory/name).exists() else 0 for name in payload['collections']}
            marker = block_path/(process_id+'.commit.json')
            save(marker,payload)
            publish_commit(directory,marker,payload,state,identities)
            print(json.dumps(completion), flush=True)
            if (record['returncode'] or not completion['measurement_command_ok'] or
                    any(row['oracle']['status'] != 'passed' for row in rows+normalized)):
                state.update(status='failed', failed_process=process_id)
                save(directory/'state.json', state)
                raise RuntimeError('CC-4 mismatch/crash/measurement control failure; affected timings invalid, preserved for repair')
            frequency_rows.extend({key:row.get(key) for key in
                ('config_id','process_round_id','rep','warmup','freq_start_khz','freq_end_khz')}
                | ({'frequency_samples_khz':row['frequency_samples_khz']} if 'frequency_samples_khz' in row else {})
                for row in normalized)
        # Compact sidecar, once per workload block. Raw observations remain
        # append-only; analysis joins config/process/rep/warmup identities.
        from .audit import frequency_flags
        save(directory/'frequency-flags.json',frequency_flags(frequency_rows))
    require_frozen(provenance)
    from .audit import frequency_flags
    save(directory/'frequency-flags.json',frequency_flags(frequency_rows))
    state.update(status='passed', finished_utc=now())
    save(directory/'state.json', state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--suite', choices=('pilot', 'training', 'evaluation'), default='evaluation')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--quiescence-record', type=Path)
    parser.add_argument('--thresholds', type=Path)
    parser.add_argument('--reps', type=int)
    parser.add_argument('--resume', action='store_true', help='resume an interrupted identical source/plan session')
    args = parser.parse_args()
    if args.prepare:
        result = prepare(args.config, args.directory, suite=args.suite)
    elif args.plan and args.quiescence_record:
        result = execute(args.plan, args.directory, args.quiescence_record,
                         repetitions=args.reps, thresholds=args.thresholds, resume=args.resume)
    else:
        plan = matrix.make_plan(matrix.load(args.config), training=args.suite == 'training', pilot=args.suite == 'pilot')
        result = {'status': 'plan-only', 'workloads': len(plan),
                  'requests_per_round': sum(len(workload['requests']) for workload in plan)}
    print(json.dumps(result, indent=2))

if __name__ == '__main__': main()
