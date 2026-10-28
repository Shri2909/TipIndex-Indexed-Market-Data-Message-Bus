#!/usr/bin/env python3
"""Run the approved P6 pilot, calibration and full matrices, with saved stages.

Default is a plan. Execution needs independently verified final core checks,
prepared independent oracles, and a truthful saved quiescence declaration.
No builds, research, source changes or data preparation occur during execution.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'py'))
from tiplog_py.exp.audit import audit_file, pilot_cv
from tiplog_py.exp.auto import calibrate
from tiplog_py.exp.matrix import load
from tiplog_py.exp.run import read_json, save, require_frozen


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def response(micro_rows, tip_rows):
    """The response is declared before viewing any evaluation measurements."""
    micro = pilot_cv(micro_rows, limit=.03)
    tip = pilot_cv(tip_rows, limit=.05)
    return {'status': 'decided', 'M1': micro, 'T1': tip,
            'micro_repetitions': 30 if micro['response_required'] else 15,
            'end_to_end_repetitions': 20 if tip['response_required'] else 10,
            'rule': 'CV above 3% M1 /5% T1 doubles baseline repetitions; all noisy observations retained',
            'limits': 'More repetitions improve uncertainty estimation; low CV does not establish absence of measurement bias.'}


def saved_micro_session(previous: dict | None, kind: str, repetitions: int,
                        local_record: Path, latest_pointer: Path) -> Path | None:
    """Prefer an owned session; never let a later mutable pointer replace it."""
    if local_record.exists():
        saved = read_json(local_record)
        return ROOT / saved['output_directory'] / 'session.json'
    if not previous:
        return None
    if previous.get('child_session'):
        return Path(previous['child_session'])
    # Recover the narrow interruption window before the parent saved its binding.
    if latest_pointer.exists():
        candidate = read_json(latest_pointer)
        config = candidate.get('configuration', {})
        if (config.get('kind') == kind and config.get('repetitions') == repetitions
                and candidate.get('started_utc', '') >= previous['started_utc']):
            return ROOT / candidate['output_directory'] / 'session.json'
    raise RuntimeError('Interrupted micro stage has no attributable saved session; preserve and inspect: ' + kind)


def consolidate(paths: list[Path], destination: Path) -> dict:
    """Publish only a complete, verified concatenation; retain interrupted copies."""
    expected = hashlib.sha256()
    sources = []
    for path in paths:
        own = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                expected.update(block)
                own.update(block)
        sources.append({'path': str(path), 'sha256': own.hexdigest()})
    identity = expected.hexdigest()
    if destination.exists() and sha(destination) != identity:
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        destination.rename(destination.with_name(destination.name + '.interrupted-' + stamp))
    if not destination.exists():
        import shutil
        temporary = destination.with_suffix(destination.suffix + '.partial')
        with temporary.open('wb') as output:
            for path in paths:
                with path.open('rb') as source:
                    shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        if sha(temporary) != identity:
            raise RuntimeError('consolidated observations differ from their frozen sources')
        temporary.replace(destination)
    return {'rows_path': str(destination), 'sha256': identity, 'sources': sources,
            'pilot_and_training_excluded': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--quiescence-record', type=Path)
    parser.add_argument('--fuzz-verification', type=Path,
                        default=Path('results/p6/fuzz-prefix-final-verified.json'))
    parser.add_argument('--prepared', type=Path, default=Path('results/raw/P6'))
    args = parser.parse_args()
    plan = ['pilot-M1:30', 'pilot-T1:30 separate processes', 'CV response',
            'training:8 independent synthetic workloads', 'Auto freeze and protocol freeze',
            'M1/M1-touch:900 cases', 'M2:120 cases', 'M3:8 cases',
            'evaluation:41 workloads, all required T configurations',
            'independent saved-output audit', 'consolidation and F01–F13 regeneration']
    if not args.run:
        print(json.dumps({'status': 'plan-only', 'stages': plan}, indent=2))
        return 0
    if args.directory is None or args.quiescence_record is None:
        parser.error('--run needs --directory and --quiescence-record')
    os.chdir(ROOT)
    os.environ.setdefault('PYTHONPATH', str(ROOT / 'py'))
    observer = set(os.sched_getaffinity(0)) - {2, 3}
    if not observer:
        raise RuntimeError('campaign controller requires CPU outside2/3')
    os.sched_setaffinity(0, observer)
    for artifact in (args.fuzz_verification, Path('results/p6/CC2-all-configurations.json'),
                     Path('results/p6/rc3-final-verified.json')):
        if read_json(artifact).get('status') != 'passed':
            raise ValueError('unmet final correctness prerequisite: ' + str(artifact))
    prepared = {suite: args.prepared / f'prepared-{suite}/plan.json'
                for suite in ('pilot', 'training', 'evaluation')}
    for suite, path in prepared.items():
        item = read_json(path)
        if item['status'] != 'prepared' or item['suite'] != suite:
            raise ValueError('independent oracle preparation incomplete: ' + str(path))
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=args.resume)
    lock_path = ROOT / 'build/p6/campaign.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state_path = directory / 'campaign.json'
    if args.resume:
        state = read_json(state_path)
        if state['prepared'] != {k: str(v) for k, v in prepared.items()}:
            raise ValueError('resume prepared inputs differ')
        require_frozen(read_json(directory / 'campaign-provenance.json'))
    else:
        import run_p5_pilot as helpers
        helpers.require_quiet(args.quiescence_record)
        provenance = helpers.provenance()
        for parent in (ROOT / 'py/tiplog_py', ROOT / 'configs'):
            provenance['source_files'].extend(helpers.identity(path) for path in sorted(parent.rglob('*'))
                if path.is_file() and '__pycache__' not in path.parts)
        provenance['binaries'].extend(helpers.identity(ROOT / 'build/release' / name)
                                     for name in ('index_bench', 'tiplog_bench'))
        save(directory / 'campaign-provenance.json', provenance)
        state = {'status': 'running', 'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                 'command': sys.argv, 'prepared': {k: str(v) for k, v in prepared.items()},
                 'stages': {}, 'evaluation_rows_used_for_calibration': 0}
        save(state_path, state)

    def stage(name, argv, *, micro_pointer=None):
        previous = state['stages'].get(name)
        if previous and previous['status'] == 'passed':
            return previous
        attempt = 1 if previous is None else previous['attempt'] + 1
        stdout, stderr = directory / f'{name}-attempt{attempt:03}.stdout.log', directory / f'{name}-attempt{attempt:03}.stderr.log'
        record = {'status': 'running', 'attempt': attempt, 'argv': argv,
                  'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'stdout': str(stdout), 'stderr': str(stderr)}
        if micro_pointer is not None and '--resume' in argv:
            record['child_session'] = argv[argv.index('--resume') + 1]
        if previous:
            save(directory / f'{name}-attempt{previous["attempt"]:03}.stage.json', previous)
        state['stages'][name] = record
        save(state_path, state)
        print(json.dumps({'stage': name, 'status': 'starting', 'stdout': str(stdout)}), flush=True)
        with stdout.open('w') as out, stderr.open('w') as err:
            child = subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=err)
            while True:
                if micro_pointer is not None and 'child_session' not in record and micro_pointer.exists():
                    candidate = read_json(micro_pointer)
                    if candidate.get('started_utc', '') >= record['started_utc']:
                        record['child_session'] = str(ROOT / candidate['output_directory'] / 'session.json')
                        save(state_path, state)
                try:
                    child.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        record.update(returncode=child.returncode, status='passed' if child.returncode == 0 else 'failed',
                      finished_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      stdout_sha256=sha(stdout), stderr_sha256=sha(stderr))
        save(state_path, state)
        if child.returncode:
            raise RuntimeError('campaign stage failed; evidence preserved: ' + name)
        return record

    def tip(suite, repetitions):
        destination = directory / suite
        command = [sys.executable, '-m', 'tiplog_py.exp.run', 'configs/P6/matrix.toml',
                   '--suite', suite, '--plan', str(prepared[suite]),
                   '--directory', str(destination), '--quiescence-record', str(args.quiescence_record),
                   '--reps', str(repetitions)]
        if suite == 'evaluation':
            command.extend(['--thresholds', 'results/p6/auto-thresholds.json'])
        if (destination / 'state.json').exists():
            saved = read_json(destination / 'state.json')
            if saved['status'] == 'failed':
                raise RuntimeError('failed session needs an explicit repaired attempt: ' + str(destination))
            command.append('--resume')
        stage(suite, command)
        result = audit_file(destination / 'runs.jsonl', measured_repetitions=repetitions)
        if result['status'] != 'passed':
            raise RuntimeError('repetition/outcome/affinity audit failed: ' + suite)
        stage(suite + '-independent-audit', [sys.executable, 'scripts/check_p6_experiments.py',
              '--plan', str(prepared[suite]), '--directory', str(destination), '--repetitions', str(repetitions)])
        return destination / 'runs.jsonl'

    def micro(kind, repetitions):
        record_path = directory / (kind + '.session.json')
        pointer = ROOT / f'results/p6/micro-{kind}-latest.json'
        previous = state['stages'].get(kind)
        owned = saved_micro_session(previous, kind, repetitions, record_path, pointer)
        command = [sys.executable, 'scripts/run_p6_micro.py', '--kind', kind, '--run',
                   '--repetitions', str(repetitions), '--quiescence-record', str(args.quiescence_record)]
        if owned is not None:
            command.extend(['--resume', str(owned)])
        stage(kind, command, micro_pointer=pointer)
        if record_path.exists():
            saved = read_json(record_path)
        else:
            bound = state['stages'][kind].get('child_session')
            saved = read_json(bound or owned or pointer)
            save(record_path, saved)
        if saved['status'] != 'passed':
            raise RuntimeError('micro campaign has no passed terminal record: ' + kind)
        return ROOT / saved['output_directory'] / 'runs.jsonl'

    pilot_micro = micro('pilot-M1', 30)
    pilot_tip = tip('pilot', 30)
    decision_path = directory / 'pilot-response.json'
    if not decision_path.exists():
        decision = response(rows(pilot_micro), rows(pilot_tip))
        decision.update(M1_raw=str(pilot_micro), M1_raw_sha256=sha(pilot_micro),
                        T1_raw=str(pilot_tip), T1_raw_sha256=sha(pilot_tip))
        save(decision_path, decision)
        save(ROOT / 'results/p6/pilot-response.json', decision)
    decision = read_json(decision_path)
    training = tip('training', decision['end_to_end_repetitions'])
    threshold_path = ROOT / 'results/p6/auto-thresholds.json'
    local_threshold_path = directory / 'auto-thresholds.json'
    expected_threshold = calibrate(rows(training), load('configs/P6/matrix.toml')['auto'], local_threshold_path)
    if threshold_path.exists() and read_json(threshold_path) != expected_threshold:
        raise RuntimeError('existing frozen Auto thresholds belong to another training cohort')
    if not threshold_path.exists():
        save(threshold_path, expected_threshold)
    protocol_path = ROOT / 'results/p6/protocol-freeze.json'
    if not protocol_path.exists():
        save(protocol_path, {'status': 'frozen', 'frozen_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'pilot_response': str(decision_path), 'pilot_response_sha256': sha(decision_path),
            'thresholds': str(threshold_path.relative_to(ROOT)), 'thresholds_sha256': sha(threshold_path),
            'micro_repetitions': decision['micro_repetitions'],
            'end_to_end_repetitions': decision['end_to_end_repetitions'],
            'settle_seconds_per_block': 60, 'cache_treatments': ['repeat-warm', 'scratch-thrashed'],
            'paired_rounds': 'Shared trace/generator state, seeded shuffled arms, fresh child each workload/round',
            'micro_design': 'Independent random-interleaved repetitions; no invented process pairing',
            'statistics': 'Seeded10000-resample percentile bootstrap, whole paired rounds for paired ratios',
            'counters': None, 'privileged_settings_changed': False,
            'provenance': str(directory / 'campaign-provenance.json'),
            'evaluation_observations_used': 0})
    elif (read_json(protocol_path).get('pilot_response_sha256') != sha(decision_path)
          or read_json(protocol_path).get('thresholds_sha256') != sha(threshold_path)):
        raise RuntimeError('existing protocol freeze belongs to another pilot or training cohort')
    micro_inputs = [micro(kind, decision['micro_repetitions']) for kind in ('M1', 'M2', 'M3')]
    evaluation = tip('evaluation', decision['end_to_end_repetitions'])
    require_frozen(read_json(directory / 'campaign-provenance.json'))
    combined = directory / 'evaluation-observations.jsonl'
    input_files = micro_inputs + [evaluation]
    save(ROOT / 'results/p6/analysis-inputs.json', consolidate(input_files, combined))
    stage('figures', [sys.executable, '-m', 'tiplog_py.figures.build', '--all'])
    state.update(status='measurements-and-figures-passed-report-pending',
                 finished_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    save(state_path, state)
    print(json.dumps({'status': state['status'], 'campaign': str(state_path)}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
