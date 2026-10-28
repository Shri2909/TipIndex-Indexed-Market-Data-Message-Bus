"""Final P1-P5 acceptance/provenance audit; no new implementation or tests."""
import datetime
import hashlib
import json
from pathlib import Path

def read(name):
    return json.loads(Path(name).read_text())

def digest(name):
    return hashlib.sha256(Path(name).read_bytes()).hexdigest()

checks = {}
for phase in ('p1', 'p2', 'p3', 'p4', 'p5'):
    gate = read(f'results/{phase}/phase-gate.json')
    checks[f'{phase}: gate passed'] = gate['status'] == 'passed'
    if phase == 'p5':
        checks['P5: all16 criteria met'] = len(gate['criteria']) == 16 and all(
            state == 'met' for state in gate['criteria'].values())
        checks['P5: all referenced check artifacts exist'] = all(
            Path(name).is_file() for name in gate['checks'].values())
for name in ('fuzz-gate-verified.json', 'F3-independent-review.json',
             'CC2-all-configurations.json', 'CC2-independent-review.json',
             'rc3-summary.json', 'rc3-integrity.json', 'pilot-latest.json',
             'pilot-audit.json', 'pilot-independent-review.json',
             'pilot-summary.json', 'cachegrind-summary.json', 'document-checks.json'):
    checks[f'accepted P5 evidence: {name}'] = read('results/p5/' + name)['status'] == 'passed'
manifest = read('results/p5/implementation-manifest.json')
checks['all94 implementation source hashes match'] = len(manifest['files']) == 94 and all(
    digest(name) == value for name, value in manifest['files'].items())
checks['all38 accepted binary hashes match'] = len(manifest['binary_sha256']) == 38 and all(
    digest(name) == value for name, value in manifest['binary_sha256'].items())
checks['all11 accepted evidence hashes match'] = all(
    digest('results/p5/' + name) == value
    for name, value in manifest['accepted_evidence_sha256'].items())
checks['master prompt unchanged'] = digest('MASTER_PROJECT_PROMPT.md') == (
    '89c0fe2ab7be8304d5cf9b9b8da07ee554efffc9c75596822fdd4f353f7d3067')
checks['managed git preserved empty and0555'] = (
    (Path('.git').stat().st_mode & 0o777) == 0o555 and not list(Path('.git').iterdir()))
summary = read('results/p5/pilot-summary.json')
rows = [json.loads(line) for line in Path(summary['normalized_repetitions']).read_text().splitlines()]
checks['normalized repetition identity and285 rows'] = (
    digest(summary['normalized_repetitions']) == summary['normalized_repetitions_sha256']
    and len(rows) == 285)
checks['every repetition has actual revision dirty flags build flags and provenance'] = all(
    row['git_sha'] == manifest['source_revision'] and isinstance(row['git_dirty'], bool)
    and all(flag in row['compile_command_with_flags'] for flag in ('-O2', '-g', '-march=x86-64-v3', '-std=c++20'))
    and Path(row['raw_json_reference']).is_file() and Path(row['provenance_reference']).is_file()
    and Path(row['environment_reference']).is_file() for row in rows)
checks['P5 live state complete and no pending work'] = (
    read('results/p5/live-state.json')['status'] == 'complete'
    and read('results/p5/live-state.json')['pending'] == [])
checks['all prior phase criteria retained'] = all(
    read(f'results/{phase}/phase-gate.json')['status'] == 'passed'
    for phase in ('p1', 'p2', 'p3', 'p4'))
result = {
    'status': 'passed' if all(checks.values()) else 'failed',
    'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'checks': checks, 'check_count': len(checks),
    'errors': [name for name, passed in checks.items() if not passed],
    'script_sha256': digest(Path(__file__)),
    'phase_boundary': 'Stopped after P5; P6-P8/Tier C/roadmap unstarted and unauthorized',
}
Path('results/p5/final-artifact-checks.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
raise SystemExit(result['status'] != 'passed')
