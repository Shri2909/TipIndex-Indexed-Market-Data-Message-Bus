#!/usr/bin/env python3
"""Retain this audit's commands, logs, source identities and host observations."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from check_remediation import input_sets
from build_provenance import capture_build, command_build


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sources():
    paths = [p for name in ('src', 'py', 'tools', 'tests', 'scripts', 'bench', 'cmake', 'configs', '.github', 'docs')
             for p in (ROOT/name).rglob('*') if p.is_file()
             and not any(x in p.parts for x in ('__pycache__', '.pytest_cache', 'corpus'))]
    paths += list(ROOT.glob('*.md')) + list(ROOT.glob('CMake*')) + [ROOT/'.gitignore']
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}


def main():
    label, *command = sys.argv[1:]
    if command[:1] == ['--']:
        command = command[1:]
    if not command or not label or Path(label).name != label:
        raise SystemExit('simple label and command required')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    prefix = RUN/'evidence'/(label+'-'+stamp)
    log = Path(str(prefix)+'.log')
    record_path = Path(str(prefix)+'.json')
    env = dict(os.environ)
    for k, v in {'PYTHONPATH': str(ROOT/'py'), 'PYTHONDONTWRITEBYTECODE': '1',
                 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'MPLCONFIGDIR': str(ROOT/'build/matplotlib'),
                 'ASAN_OPTIONS': 'detect_leaks=1:abort_on_error=1',
                 'UBSAN_OPTIONS': 'print_stacktrace=1:halt_on_error=1'}.items():
        env.setdefault(k, v)
    before = sources()
    input_before = input_sets(ROOT)
    execution = command_build(command, ROOT)
    record = {'argv': command, 'cwd': str(ROOT), 'label': label,
              'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'sources_before': before, 'environment': {k: env.get(k) for k in
              ('PATH', 'ASAN_OPTIONS', 'UBSAN_OPTIONS', 'PYTHONPATH', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD',
               'PYTHONDONTWRITEBYTECODE', 'MPLCONFIGDIR', 'TIPLOG_FUZZ_MODE')},
              'load_before': os.getloadavg(), 'affinity': sorted(os.sched_getaffinity(0)),
              'log': str(log.relative_to(ROOT))}
    for key in ('GTEST_FILTER','GTEST_TOTAL_SHARDS','GTEST_SHARD_INDEX','GTEST_REPEAT','TESTBRIDGE_TEST_ONLY','CTEST_TESTS_TO_RUN',
                'PYTEST_ADDOPTS','PYTEST_PLUGINS','PYTEST_DISABLE_PLUGIN_AUTOLOAD'):
        record['environment'][key] = env.get(key)
    record['input_sets_before'] = input_before
    if execution:
        record['build_execution'] = execution
        if execution['kind'] != 'build':
            record['build_artifacts_before'] = capture_build(ROOT, execution['preset'], input_before['cpp'])
    binary = ROOT/command[0]
    if binary.is_file():
        record['executable_sha256_before'] = sha(binary)
    record_path.write_text(json.dumps(record, indent=2)+'\n')
    start = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    with log.open('x') as output:
        try:
            code = subprocess.run(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT).returncode
        except OSError as error:
            output.write(str(error)+'\n')
            code = 127
    used = resource.getrusage(resource.RUSAGE_CHILDREN)
    record.update(exit_code=code, elapsed_seconds=time.monotonic()-start,
                  child_user_seconds=used.ru_utime-usage.ru_utime,
                  child_system_seconds=used.ru_stime-usage.ru_stime,
                  child_maxrss_kib=used.ru_maxrss, sources_after=sources(),
                  log_sha256=sha(log), load_after=os.getloadavg())
    record['input_sets_after'] = input_sets(ROOT)
    record['status'] = 'passed' if code == 0 else 'failed'
    if execution:
        record['build_artifacts_after'] = capture_build(ROOT, execution['preset'], record['input_sets_after']['cpp'])
        if execution['kind'] == 'build' and execution['full_build'] and code == 0:
            record['build_provenance'] = record['build_artifacts_after']
        elif execution['kind'] != 'build' and record['build_artifacts_before'] != record['build_artifacts_after']:
            record['exit_code'] = code = 125
            record['status'] = 'failed'
            record['provenance_error'] = 'artifacts changed during execution'
    if binary.is_file():
        record['executable_sha256_after'] = sha(binary)
    record['sources_stable'] = before == record['sources_after']
    record_path.write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({'label': label, 'exit_code': code, 'sources_stable': record['sources_stable'],
                      'elapsed_seconds': record['elapsed_seconds'], 'record': str(record_path.relative_to(ROOT))}), flush=True)
    if code:
        print(log.read_text(errors='replace')[-5000:], flush=True)
    return code if code >= 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
