#!/usr/bin/env python3
"""Assemble this approved remediation phase's reviewed source/evidence inventory.

This writes only the new acceptance.json; it never edits historical identities
or manufactures test results. Run check_remediation.py to verify the candidate.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('remediation', ROOT / 'scripts/check_remediation.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
OUT = ROOT / 'audit/remediation'


def relative(path):
    return path.relative_to(ROOT).as_posix()


def latest(label):
    paths = sorted((OUT / 'checks').glob(label + '-*.json'))
    if not paths:
        raise ValueError('missing executed command: ' + label)
    path = paths[-1]
    record = json.loads(path.read_text())
    if record['status'] != 'passed' or record['exit_code'] != 0:
        raise ValueError('last execution failed: ' + str(path))
    return {'record': relative(path)}


def main():
    checks = {}
    for preset in checker.PRESETS:
        for step in ('configure', 'build', 'ctest'):
            prefix = 'asan' if preset == 'asan-ubsan' and step == 'ctest' else preset
            checks[f'{preset}-{step}'] = latest(f'{prefix}-bound-{step}')
        xml = 'audit/remediation/' + ('asan' if preset == 'asan-ubsan' else preset) + '.xml'
        checks[f'{preset}-ctest'].update(junit=xml, tests=len(list(ET.parse(ROOT / xml).iter('testcase'))))
    for label, command_label, xml in (
        ('python-root', 'python-bound-tests', 'audit/remediation/python.xml'),
        ('python-from-py', 'python-bound-from-py', 'audit/remediation/python-from-py.xml'),
        ('experiment-auditor', 'auditor-bound-self-test', None),
        ('pip-check', 'pip-bound-check', None)):
        checks[label] = latest(command_label)
        if xml:
            checks[label].update(junit=xml, tests=len(list(ET.parse(ROOT / xml).iter('testcase'))))
    evidence = {}
    for path in sorted(OUT.rglob('*')):
        if not path.is_file() or path == OUT / 'acceptance.json' or path == OUT / 'checks.json':
            continue
        if any(part.endswith(('-corpus', '-artifacts')) or part == '__pycache__' for part in path.parts):
            continue
        if path.suffix in {'.partial', '.pyc', '.pyo'} or path.name.startswith('closeout-'):
            continue
        evidence[relative(path)] = {'sha256': checker.digest(path), 'bytes': path.stat().st_size}
    auxiliary = ['audit/AUDIT_REPORT.md', 'results/p7/input-manifest.json',
                 'results/p7/cc5-release.json', 'results/p7/worked-example.json',
                 'results/p6/auditor-t5-compatibility/measurement-files-before.json']
    for name in auxiliary:
        path = ROOT / name
        evidence[name] = {'sha256': checker.digest(path), 'bytes': path.stat().st_size}
    core = 'audit/remediation/core.md'
    python = 'audit/remediation/python.md'
    tools = 'audit/remediation/tools.md'
    finding_evidence = {
        1: [core, python, tools], 2: [core], 3: [core, 'audit/remediation/core/mutation-summary.json'],
        4: [core, 'audit/remediation/core/final-validation/summary.json'], 5: [python, tools],
        6: [python, 'audit/remediation/python-from-py.xml'],
        7: ['audit/remediation/pip-audit.json', 'audit/remediation/dependency-lock.json'],
        8: [core], 9: [python], 10: ['audit/remediation/dependency-lock.json',
                                    'audit/remediation/ci-dependency-lock.json'],
        11: [core, python, tools], 12: [core, 'audit/remediation/core/final-validation/summary.json'],
        13: [tools], 14: [python, 'audit/remediation/core/review-confirmation.json'],
        15: [python, 'audit/remediation/core/review-confirmation.json'], 16: [python],
        17: [python], 18: [python], 19: [python], 20: [core], 21: [core], 22: [tools],
        23: [tools], 24: [tools], 25: ['audit/remediation/historical-quiescence.json'],
        26: ['audit/remediation/reconcile-baseline.json', 'audit/remediation/reconcile-semantic.json',
             'audit/remediation/tools/frozen-p6-measurements.json']}
    manifest = {
        'schema': checker.SCHEMA, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'phase': 'User-approved audit fixes after P8',
        'authorization': 'Fix the approved audit plan, then stop before work-budgeted replay/tail polling.',
        'findings': {f'AUD-{number:03}': {'status': 'closed', 'evidence': paths}
                     for number, paths in finding_evidence.items()},
        'observations': {f'OBS-{number:02}': {'status': 'resolved', 'evidence': [tools] if number < 5
                                           else [tools, checks['python-root']['record']]}
                         for number in range(1, 6)},
        'deferred_features': ['F-01'], 'sources': checker.source_inventory(ROOT),
        'input_sets': checker.input_sets(ROOT), 'executed_checks': checks, 'evidence': evidence,
        'limits': ['Historical performance/fuzz campaigns remain historical.',
                   'No fresh quiet-host throughput or latency claim; hosted CI has not run.',
                   'Multi-output rename rollback covers handled failures, not whole-bundle power-loss atomicity.',
                   'Acquisition checksum rejection was tested with mocked transfer, not a new Nasdaq download.']}
    destination = OUT / 'acceptance.json'
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'candidate': relative(destination), 'sources': len(manifest['sources']),
                      'evidence': len(evidence), 'findings': len(finding_evidence)}))


if __name__ == '__main__':
    main()
