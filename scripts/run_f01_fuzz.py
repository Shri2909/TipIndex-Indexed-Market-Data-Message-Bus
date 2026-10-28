#!/usr/bin/env python3
"""Run F-01 fuzz regression using private writable corpus copies."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    destination = ROOT / 'build/f01' / f'fuzz-{stamp}'
    destination.mkdir(parents=True)
    outcomes = []
    for target, original in (('fuzz_trace_reader', 'trace_reader'), ('fuzz_itch_walker', 'itch_walker'),
                             ('fuzz_engine_ops', 'ops_integrated'), ('fuzz_poll_budget', None)):
        directory = destination / target
        corpus = directory / 'corpus'
        corpus.mkdir(parents=True)
        if original:
            paths = sorted(path for path in (ROOT / 'tests/fuzz/corpus' / original).rglob('*') if path.is_file())
            # At most 128 evenly spaced historical seeds; copies may evolve.
            selected = paths if len(paths) <= 128 else [paths[i * len(paths) // 128] for i in range(128)]
            seeds = {str(p.relative_to(ROOT)): sha(p) for p in selected}
            for i, path in enumerate(selected):
                shutil.copyfile(path, corpus / f'seed-{i}')
        else:
            seeds = {}
            for i in range(64):
                generator = random.Random(20261026 + i)
                path = corpus / f'synthetic-{i}'
                path.write_bytes(bytes(generator.randrange(256) for _ in range(2049)))
                seeds[path.name] = sha(path)
        log = directory / 'stderr.log'
        binary = ROOT / 'build/fuzz' / target
        command = [str(binary), str(corpus), '-runs=10000', '-max_len=4096',
                   f'-artifact_prefix={directory}/', '-print_final_stats=1']
        environment = dict(os.environ, TIPLOG_FUZZ_MODE='all')
        environment.setdefault('ASAN_OPTIONS', 'detect_leaks=1:abort_on_error=1')
        environment.setdefault('UBSAN_OPTIONS', 'print_stacktrace=1:halt_on_error=1')
        with log.open('w') as output:
            code = subprocess.run(command, cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT).returncode
        content = log.read_text(errors='replace')
        completed = re.findall(r'#(\d+)\s+DONE', content)
        passed = code == 0 and completed and int(completed[-1]) >= 10000
        outcome = {'target': target, 'status': 'passed' if passed else 'failed', 'exit_code': code,
                   'argv': command, 'binary_sha256': sha(binary), 'initial_seeds': seeds,
                   'completed_executions': int(completed[-1]) if completed else 0,
                   'raw_log': str(log.relative_to(ROOT)), 'raw_log_sha256': sha(log),
                   'environment': {key: environment[key] for key in ('TIPLOG_FUZZ_MODE', 'ASAN_OPTIONS', 'UBSAN_OPTIONS')}}
        outcomes.append(outcome)
        print(json.dumps({key: outcome[key] for key in ('target', 'status', 'exit_code', 'completed_executions')}), flush=True)
        if not passed:
            break
    summary = ROOT / 'results/f01' / f'fuzz-{stamp}.json'
    summary.write_text(json.dumps({'status': 'passed' if len(outcomes) == 4 and all(x['status'] == 'passed' for x in outcomes) else 'failed',
                                   'scope': '128 or fewer evenly spaced copied historical seeds per old target; 64 synthetic new-grammar seeds. Raw logs/corpora stay in ignored build/f01.',
                                   'targets': outcomes}, indent=2) + '\n')
    print(json.dumps({'summary': str(summary.relative_to(ROOT))}), flush=True)
    return 0 if len(outcomes) == 4 and all(x['status'] == 'passed' for x in outcomes) else 1


if __name__ == '__main__':
    raise SystemExit(main())
