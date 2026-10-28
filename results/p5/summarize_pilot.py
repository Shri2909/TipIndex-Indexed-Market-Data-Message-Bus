"""Save limited P5 pilot rows with per-row build/run provenance."""
import datetime
import hashlib
import json
from pathlib import Path

session = json.loads(Path('results/p5/pilot-latest.json').read_text())
audit = json.loads(Path('results/p5/pilot-audit.json').read_text())
assert session['status'] == audit['status'] == 'passed'
base = Path(session['output_directory'])
commands = json.loads(Path('build/release/compile_commands.json').read_text())
output = Path('results/p5/pilot-repetitions.jsonl')
rows, groups = [], []
for block in session['blocks']:
    directory = base / block['label']
    raw = json.loads((directory / 'gbench.json').read_text())
    filename = 'merge_bench.cpp' if block['label'] == 'M1' else 'publish_bench.cpp'
    compile_command = next(c['command'] for c in commands if Path(c['file']).name == filename)
    for row in raw['benchmarks']:
        if row.get('run_type') != 'iteration':
            continue
        rows.append({**row, 'pilot_run_id': session['run_id'],
                     'block': block['label'], 'cpu': 2, 'input_seed': 20191230,
                     'git_sha': session['provenance']['git']['sha'],
                     'git_dirty': session['provenance']['git']['dirty'],
                     'compile_command_with_flags': compile_command,
                     'aslr_regime': session['aslr_regime'],
                     'provenance_reference': str(base / 'provenance.json'),
                     'environment_reference': str(base / 'environment.json'),
                     'raw_json_reference': str(directory / 'gbench.json'),
                     'scope': 'Limited P5 pilot repetition; no full-matrix or calibrated-Auto claim'})
    groups.extend({'block': block['label'], **group} for group in block['summary']['groups'])
assert len(rows) == 285 and sum(group['non_ok_count'] for group in groups) == 0
output.write_text(''.join(json.dumps(row) + '\n' for row in rows))
summary = {
    'status': 'passed',
    'saved_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'session': str(base / 'session.json'), 'session_sha256': audit['session_sha256'],
    'audit': 'results/p5/pilot-audit.json', 'audit_checks': len(audit['checks']),
    'individual_repetitions': 285, 'function_invocations': audit['audited_invocations'],
    'profiles': 19, 'repetitions_per_profile': 15, 'non_ok_repetitions': 0,
    'frequency_flagged_endpoints': session['frequency_flags']['flagged_samples'],
    'frequency_total_endpoints': len(session['frequency_flags']['samples']),
    'frequency_session_median_khz': session['frequency_flags']['session_median_khz'],
    'frequency_policy': 'All flagged endpoints/invocations/repetitions retained; endpoints do not prove constant frequency',
    'aslr_regime': session['aslr_regime'],
    'source_binary_changes': session['source_binary_changes'],
    'normalized_repetitions': str(output),
    'normalized_repetitions_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
    'groups': sorted(groups, key=lambda g: g['profile']),
    'limits': ['Selected k64 profiles and fixed64/P100 M2 only',
               'Descriptive pilot medians, no confidence-interval/kernel-winner/generalized speedup claim',
               'Whole-child/invocation diagnostics include setup; primary measurements are GBench hot-loop rows',
               'P6 full matrix, noise study, real-trace timing and held-out Auto calibration unrun',
               'No hardware-counter or constant-clock/exclusive-host claim'],
}
Path('results/p5/pilot-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
lines = ['# P5 limited pilot results — 2026-10-19', '',
         'All three isolated blocks passed; the independent auditor passed '
         f"{summary['audit_checks']} checks over285 measured rows and369 logged invocations. "
         'Every selected case has15 repetitions and zero non-ok outcomes.', '',
         'The table gives descriptive medians for these selected cases. '
         'M1 units are ns/output; M2 units are ns/publish. '
         'P6 full experiments, confidence intervals and calibration remain unrun.', '',
         '| Profile | n | CPU ns/item | Wall ns/item | Non-ok |',
         '|---|---:|---:|---:|---:|']
for group in summary['groups']:
    lines.append(f"| {group['profile']} | {group['n']} | {group['median_cpu_ns_per_item']:.3f} | "
                 f"{group['median_wall_ns_per_item']:.3f} | {group['non_ok_count']} |")
lines.extend(['',
    f"Frequency: {summary['frequency_flagged_endpoints']} of{summary['frequency_total_endpoints']} "
    'sampled endpoints exceed10% of the session median. All associated data remain retained. '
    'These endpoints include setup and do not identify constant hot-loop clocks or exact affected measured rows.', '',
    'Fresh AC/P-core/CPU2 checks passed, each block settled for at least60 monotonic seconds, '
    'and no project fuzzing/tests/builds/conversion ran concurrently. The observer excluded CPUs2–3. '
    'Visible-process snapshots and sibling CPU observations do not prove exclusive host access. '
    'The fresh per-process ASLR probe succeeded and measured children used setarch-R; '
    'system settings remained unchanged.', '',
    '[Session and raw directory](../../' + str(base / 'session.json') + '), '
    '[independent audit](pilot-audit.json), [summary](pilot-summary.json), '
    '[per-repetition build/run provenance](pilot-repetitions.jsonl), '
    '[method](pilot-method.md), [whole-process simulated Cachegrind](cachegrind-summary.json).', '',
    'All source/binary/input/raw-file identities match. M1 output/input hashes match independently '
    'sorted functional references. Every M2 adaptive prefix matches an independent closed-form '
    'sequence digest and count, including actual prefill/zero-pressure state. '
    'Whole-child/user/system diagnostics include setup and cannot substitute for hot-loop CPU time.'])
Path('results/p5/pilot-results.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({k: summary[k] for k in ('status', 'individual_repetitions', 'function_invocations', 'profiles', 'non_ok_repetitions')}))
