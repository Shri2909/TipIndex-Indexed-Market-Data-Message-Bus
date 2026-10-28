#!/usr/bin/env python3
"""Bounded current-source differential and private-corpus fuzz acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from check_remediation import digest, input_sets


def execute(label, argv, environment=None):
    before = set((RUN/'evidence').glob(label+'-*.json'))
    code = subprocess.run([sys.executable, str(RUN/'run_check.py'), label, '--', *argv],
                          cwd=ROOT, env=environment).returncode
    created = set((RUN/'evidence').glob(label+'-*.json'))-before
    if len(created) != 1:
        raise ValueError('missing/ambiguous execution record: '+label)
    path = created.pop()
    record = json.loads(path.read_text())
    if code or record['exit_code'] or record['input_sets_before']['cpp'] != record['input_sets_after']['cpp']:
        raise ValueError('failed or changing campaign: '+label)
    return path.relative_to(ROOT).as_posix(), record, (ROOT/record['log']).read_text()


def differential(preset):
    seeds = 1000 if preset == 'release' else 200
    pairs = [('scan', 'stdpq')]+[(m, k) for m in ('indexed', 'auto') for k in ('stdpq', 'binheap', 'quad', 'loser')]
    records, results = [], []
    for mode, kernel in pairs:
        name, record, log = execute(f'final-diff-{preset}-{mode}-{kernel}',
            [f'build/{preset}/tiplog_differential', '--seeds', str(seeds), '--operations', '10000', '--mode', mode, '--kernel', kernel])
        value = json.loads(log)
        assert value['status'] == 'passed' and value['operations'] == seeds*10000
        assert all(value[field] > 0 for field in ('publications', 'opens', 'nonuniform_payload_publications', 'delivered'))
        records.append(name); results.append(value)
    assert len({value['digest_fnv1a64'] for value in results}) == 1
    name, record, log = execute('final-budget-diff-'+preset,
        [f'build/{preset}/tiplog_poll_differential', '--seeds', str(seeds), '--operations', '10000'])
    budget = json.loads(log)
    assert budget['status'] == 'passed' and budget['operations'] == seeds*10000 and budget['mode_kernel_mask'] == 4095
    assert all(budget[key] > 0 for key in ('publications','replay_opens','tail_opens','polls','finite_polls',
                                         'zero_polls','inspection_yields','delivered','inspections','errors','pad_inspections'))
    records.append(name)
    result = {'status': 'passed', 'preset': preset, 'seeds_per_campaign': seeds, 'operations_per_seed': 10000,
              'legacy_pairs': pairs, 'legacy_operations': seeds*10000*9, 'budget_operations': seeds*10000,
              'records': records, 'legacy_digest': results[0]['digest_fnv1a64'], 'budget_result': budget,
              'cpp_input_set': input_sets(ROOT)['cpp']}
    (RUN/'evidence'/('differential-'+preset+'.json')).write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({key: result[key] for key in ('status','preset','legacy_operations','budget_operations')}), flush=True)


def corpus_identity():
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT/'tests/fuzz/corpus').rglob('*')) if p.is_file()}


def fuzz():
    before = corpus_identity()
    directory = RUN/'evidence/private-fuzz'
    directory.mkdir(exist_ok=False)
    outcomes = []
    for target, original in (('fuzz_trace_reader','trace_reader'), ('fuzz_itch_walker','itch_walker'),
                             ('fuzz_engine_ops','ops_integrated'), ('fuzz_poll_budget',None)):
        work = directory/target
        corpus = work/'corpus'; corpus.mkdir(parents=True)
        seeds = {}
        if original:
            paths = sorted(p for p in (ROOT/'tests/fuzz/corpus'/original).rglob('*') if p.is_file())
            chosen = paths if len(paths) <= 128 else [paths[i*len(paths)//128] for i in range(128)]
            for i, path in enumerate(chosen):
                shutil.copyfile(path, corpus/f'seed-{i}')
                seeds[str(path.relative_to(ROOT))] = digest(path)
        else:
            for i in range(64):
                generator = random.Random(20261027+i)
                seed = corpus/f'synthetic-{i}'
                seed.write_bytes(bytes(generator.randrange(256) for _ in range(2049)))
                seeds[str(seed.relative_to(ROOT))] = digest(seed)
        environment = dict(os.environ, TIPLOG_FUZZ_MODE='all', ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                           UBSAN_OPTIONS='print_stacktrace=1:halt_on_error=1')
        command = [f'build/fuzz/{target}', str(corpus), '-runs=10000', '-max_len=4096', '-seed=20261027',
                   f'-artifact_prefix={work}/', '-print_final_stats=1']
        name, record, log = execute('final-fuzz-'+target, command, environment)
        completed = re.findall(r'#(\d+)\s+DONE', log)
        assert completed and int(completed[-1]) >= 10000
        assert not re.search(r'ERROR: (?:AddressSanitizer|LeakSanitizer)|runtime error:', log)
        assert not any(work.glob('crash-*')) and not any(work.glob('leak-*'))
        outcomes.append({'target': target, 'record': name, 'completed_executions': int(completed[-1]), 'initial_seeds': seeds})
    after = corpus_identity()
    assert before == after
    result = {'status': 'passed', 'targets': outcomes, 'historical_corpora_unchanged': True,
              'historical_corpus_files': len(before), 'historical_corpus_identity': hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()}
    (RUN/'evidence/fuzz.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status':'passed','targets':len(outcomes),'executions':sum(x['completed_executions'] for x in outcomes)}),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('differential','fuzz'))
    parser.add_argument('--preset', choices=('release','asan-ubsan'))
    args = parser.parse_args()
    if args.kind == 'differential': differential(args.preset)
    else: fuzz()


if __name__ == '__main__': main()
