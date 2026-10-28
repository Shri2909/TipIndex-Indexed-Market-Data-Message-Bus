#!/usr/bin/env python3
"""Record an approved remediation check without overwriting historical phase evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from check_remediation import input_sets

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
    destination = ROOT/'audit/remediation/checks'
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
                              ('ASAN_OPTIONS', 'UBSAN_OPTIONS', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')}}
    record_path.write_text(json.dumps(record, indent=2)+'\n')
    started = time.monotonic()
    with log.open('w') as output:
        try:
            code = subprocess.run(command, cwd=working_directory, env=environment,
                                  stdout=output, stderr=subprocess.STDOUT).returncode
        except OSError as error:
            output.write(str(error)+'\n')
            code = 127
    record.update(exit_code=code, status='passed' if code == 0 else 'failed',
                  elapsed_seconds=time.monotonic()-started, log_sha256=sha(log),
                  input_sets_after=input_sets())
    record_path.write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({'status': record['status'], 'record': str(record_path.relative_to(ROOT)),
                      'exit_code': code}), flush=True)
    return code if code >= 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
