#!/usr/bin/env python3
"""Run fresh legacy and budget-aware differential campaigns for F-01."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from check_remediation import input_sets

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', choices=('release', 'asan-ubsan'), required=True)
    parser.add_argument('--reuse-compatible', action='store_true',
                        help='reuse exact completed commands from compatible frozen compiled sources')
    args = parser.parse_args()
    seeds = 1000 if args.preset == 'release' else 200
    pairs = [('scan', 'stdpq')] + [(mode, kernel) for mode in ('indexed', 'auto')
                                  for kernel in ('stdpq', 'binheap', 'quad', 'loser')]
    destination = ROOT / 'results/f01' / f'differential-{args.preset}.json'
    if destination.exists():
        parser.error('result already exists; preserve it and select a fresh campaign namespace')
    checks = ROOT / 'results/f01/checks'
    freezes = [json.loads((ROOT / 'results/f01' / name).read_text())
               for name in ('source-freeze.json', 'source-freeze-final.json')]
    changed = {name for name in set(freezes[0]['compiled_sources']) | set(freezes[1]['compiled_sources'])
               if freezes[0]['compiled_sources'].get(name) != freezes[1]['compiled_sources'].get(name)}
    if changed != {'tests/unit/poll_budget_test.cpp'}:
        parser.error('compatible reuse requires only the declared test-only change')
    if input_sets()['cpp'] != freezes[1]['cpp_input_set']:
        parser.error('current compiled sources differ from the final feature freeze')
    allowed = {item['cpp_input_set'] for item in freezes}
    records, reused = [], []

    def execute(label, arguments):
        if args.reuse_compatible:
            for path in sorted(checks.glob(f'{label}-*.json'), reverse=True):
                saved = json.loads(path.read_text())
                if saved.get('status') != 'passed' or saved.get('exit_code') != 0 or saved.get('argv') != arguments:
                    continue
                if any(saved.get(key, {}).get('cpp') not in allowed
                       for key in ('input_sets_before', 'input_sets_after')):
                    continue
                log = ROOT / saved['log']
                if hashlib.sha256(log.read_bytes()).hexdigest() != saved['log_sha256']:
                    continue
                relative = str(path.relative_to(ROOT))
                records.append(relative); reused.append(relative)
                print(json.dumps({'status': 'reused-compatible', 'record': relative}), flush=True)
                return 0
        before = set(checks.glob('*.json'))
        code = subprocess.run([sys.executable, 'scripts/run_f01_check.py', label, '--', *arguments], cwd=ROOT).returncode
        created = set(checks.glob('*.json')) - before
        matching = [path for path in created if json.loads(path.read_text()).get('label') == label]
        if code == 0 and len(matching) == 1:
            records.append(str(matching[0].relative_to(ROOT)))
            return 0
        return 1

    for mode, kernel in pairs:
        command = [f'build/{args.preset}/tiplog_differential', '--seeds', str(seeds),
                   '--operations', '10000', '--mode', mode, '--kernel', kernel]
        if execute(f'legacy-{args.preset}-{mode}-{kernel}', command):
            return 1
    command = [f'build/{args.preset}/tiplog_poll_differential', '--seeds', str(seeds),
               '--operations', '10000']
    if execute(f'budget-{args.preset}', command):
        return 1
    destination.write_text(json.dumps({'status': 'passed', 'preset': args.preset,
                                      'seeds_per_campaign': seeds, 'operations_per_seed': 10000,
                                      'legacy_pairs': pairs, 'records': records,
                                      'reused_compatible': reused}, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
