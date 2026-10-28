#!/usr/bin/env python3
"""Record an approved F-01 check without overwriting historical phase evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from check_remediation import input_sets
from build_provenance import capture_build, command_build

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd', type=Path, default=ROOT)
    parser.add_argument('label')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or Path(args.label).name != args.label:
        parser.error('a simple label and command are required')
    working_directory = args.cwd.resolve()
    if not working_directory.is_relative_to(ROOT):
        parser.error('working directory must be inside the repository')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    destination = ROOT/'results/f01/checks'
    destination.mkdir(parents=True, exist_ok=True)
    prefix = destination/f'{args.label}-{stamp}'
    log = Path(str(prefix)+'.log')
    record_path = Path(str(prefix)+'.json')
    environment = dict(os.environ)
    environment.setdefault('PYTHONPATH', str(ROOT/'py'))
    environment.setdefault('PYTHONDONTWRITEBYTECODE', '1')
    environment.setdefault('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    environment.setdefault('MPLCONFIGDIR', str(ROOT/'build/matplotlib'))
    environment.setdefault('PIP_CACHE_DIR', str(ROOT/'build/pip-cache'))
    environment.setdefault('ASAN_OPTIONS', 'detect_leaks=1:abort_on_error=1')
    environment.setdefault('UBSAN_OPTIONS', 'print_stacktrace=1:halt_on_error=1')
    record = {'label': args.label, 'argv': command, 'cwd': str(working_directory),
              'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running',
              'input_sets_before': input_sets(),
              'log': str(log.relative_to(ROOT)),
              'environment': {key: environment.get(key) for key in
                              ('ASAN_OPTIONS', 'UBSAN_OPTIONS', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE',
                               'GTEST_FILTER', 'GTEST_TOTAL_SHARDS', 'GTEST_SHARD_INDEX', 'GTEST_REPEAT',
                               'TESTBRIDGE_TEST_ONLY', 'CTEST_TESTS_TO_RUN',
                               'PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD')}}
    provenance_error = None
    try:
        execution = command_build(command, ROOT, working_directory)
        if execution:
            record['build_execution'] = execution
            if execution['kind'] != 'build':
                record['build_artifacts_before'] = capture_build(ROOT, execution['preset'], record['input_sets_before']['cpp'])
    except (OSError, ValueError, TypeError) as error:
        provenance_error = f'{type(error).__name__}: {error}'
    record_path.write_text(json.dumps(record, indent=2)+'\n')
    started = time.monotonic()
    with log.open('w') as output:
        if provenance_error is not None:
            output.write('Build provenance preflight failed: '+provenance_error+'\n')
            code = 125
        else:
            try:
                code = subprocess.run(command, cwd=working_directory, env=environment,
                                      stdout=output, stderr=subprocess.STDOUT).returncode
            except OSError as error:
                output.write(str(error)+'\n')
                code = 127
            record['command_exit_code'] = code
    record['input_sets_after'] = input_sets()
    if provenance_error is None and record.get('build_execution'):
        execution = record['build_execution']
        try:
            record['build_artifacts_after'] = capture_build(ROOT, execution['preset'], record['input_sets_after']['cpp'])
            if (code == 0 and execution['kind'] == 'build' and execution['full_build'] and
                    record['input_sets_before']['cpp'] == record['input_sets_after']['cpp']):
                record['build_provenance'] = record['build_artifacts_after']
            if execution['kind'] != 'build' and record['build_artifacts_before'] != record['build_artifacts_after']:
                raise ValueError('build artifacts changed during execution')
        except (OSError, ValueError, TypeError) as error:
            provenance_error = f'{type(error).__name__}: {error}'
            code = 125 if code == 0 else code
            with log.open('a') as output:
                output.write('Build provenance capture failed: '+provenance_error+'\n')
    if provenance_error is not None:
        record['provenance_error'] = provenance_error
    record.update(exit_code=code, status='passed' if code == 0 else 'failed',
                  elapsed_seconds=time.monotonic()-started, log_sha256=sha(log),
                  input_sets_after=record['input_sets_after'])
    record_path.write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({'status': record['status'], 'record': str(record_path.relative_to(ROOT)),
                      'exit_code': code}), flush=True)
    return code if code >= 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
