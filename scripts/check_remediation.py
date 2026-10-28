#!/usr/bin/env python3
"""Verify the approved audit-fix evidence without rerunning historical campaigns.

The P1-P8 gates describe the original implementation. This separate closeout
binds the current sources to fresh functional checks and preserves those gates.
It performs read-only verification and writes only its requested result file.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'tiplog-remediation-acceptance-v1'
FINDINGS = {f'AUD-{number:03}' for number in range(1, 27)}
OBSERVATIONS = {f'OBS-{number:02}' for number in range(1, 6)}
PRESETS = ('debug', 'release', 'asan-ubsan', 'fuzz')
PAIRS = {('scan', 'stdpq')} | {(mode, kernel) for mode in ('indexed', 'auto')
                             for kernel in ('stdpq', 'binheap', 'quad', 'loser')}
SOURCE_DIRECTORIES = ('src', 'tools', 'bench', 'tests', 'py', 'scripts',
                      'cmake', 'configs', '.github', 'docs')
SHA = re.compile(r'[0-9a-f]{64}\Z')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def local(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'path escapes the workspace: {name}')
    return path


def source_inventory(root=ROOT):
    selected = {path for path in root.iterdir() if path.is_file()
                and (path.suffix in {'.md', '.json', '.txt'} or path.name == '.gitignore')}
    for directory in SOURCE_DIRECTORIES:
        selected.update(path for path in (root / directory).rglob('*') if path.is_file()
                        and not {'.pytest_cache', '__pycache__'}.intersection(path.parts)
                        and path.suffix not in {'.pyc', '.pyo'})
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(selected)}


def input_sets(root=ROOT):
    """Separate compiled inputs from Python inputs for executed-check binding."""
    sources = source_inventory(root)
    cpp = {name: sha for name, sha in sources.items()
           if name.startswith(('src/', 'tools/', 'bench/', 'cmake/'))
           or (name.startswith('tests/') and not name.startswith('tests/scripts/'))
           or name in ('CMakeLists.txt', 'CMakePresets.json')}
    python = {name: sha for name, sha in sources.items()
              if name.startswith(('py/', 'scripts/', 'tests/scripts/', 'configs/'))}
    return {label: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            for label, value in (('cpp', cpp), ('python', python))}


def junit_counts(path, minimum):
    document = ET.parse(path).getroot()
    cases = list(document.iter('testcase'))
    names = {(case.get('classname'), case.get('name')) for case in cases}
    if len(cases) < minimum or len(names) != len(cases):
        raise ValueError('missing or duplicate test cases')
    for element in document.iter():
        if element.tag in {'failure', 'error', 'skipped'}:
            raise ValueError('failed, errored or skipped test case')
        if element.tag in {'testsuite', 'testsuites'}:
            if any(int(element.get(key, '0')) != 0 for key in ('failures', 'errors', 'skipped', 'disabled')):
                raise ValueError('nonzero suite failure/skip count')
        if element.tag == 'testcase' and (element.get('status') in {'notrun', 'disabled'}
                                           or element.get('result') in {'skipped', 'suppressed'}):
            raise ValueError('test case did not execute')
    return len(cases)


class Audit:
    def __init__(self, manifest, root=ROOT):
        self.manifest, self.root = manifest, root
        self.checks = []
        self.evidence = manifest.get('evidence', {})

    def check(self, name, passed, details=None):
        self.checks.append({'check': name, 'status': 'passed' if passed else 'failed',
                            'details': details})
        return bool(passed)

    def section(self, name, action):
        try:
            action()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as error:
            self.check(name, False, f'{type(error).__name__}: {error}')

    def identity(self, name, expected):
        sha = expected.get('sha256') if isinstance(expected, dict) else expected
        path = local(self.root, name)
        return self.check(f'identity:{name}', isinstance(sha, str) and bool(SHA.fullmatch(sha))
                          and digest(path) == sha and (not isinstance(expected, dict)
                          or 'bytes' not in expected or path.stat().st_size == expected['bytes']))

    def read(self, name):
        if name not in self.evidence:
            raise ValueError(f'unbound evidence: {name}')
        if not self.identity(name, self.evidence[name]):
            raise ValueError(f'changed evidence: {name}')
        return json.loads(local(self.root, name).read_text())

    def sources(self):
        current = source_inventory(self.root)
        self.check('complete current source/document inventory', current == self.manifest['sources'],
                   {'files': len(current)})
        self.current_inputs = input_sets(self.root)
        self.check('current input-set identities', self.current_inputs == self.manifest['input_sets'])

    def scope(self):
        self.check('acceptance schema', self.manifest.get('schema') == SCHEMA)
        self.check('all 26 findings closed', set(self.manifest['findings']) == FINDINGS
                   and all(item['status'] == 'closed' and item['evidence']
                           for item in self.manifest['findings'].values()))
        self.check('all five observations resolved', set(self.manifest['observations']) == OBSERVATIONS
                   and all(item['status'] == 'resolved' and item['evidence']
                           for item in self.manifest['observations'].values()))
        for item in list(self.manifest['findings'].values()) + list(self.manifest['observations'].values()):
            self.check('finding evidence bound', all(name in self.evidence for name in item['evidence']))
        self.check('F-01 deferred', self.manifest['deferred_features'] == ['F-01'])
        baseline = self.read('audit/remediation/baseline.json')
        for name in ('src/tiplog/engine/engine.cpp', 'src/tiplog/engine/engine.hpp'):
            self.identity(name, baseline['files'][name])
        original = local(self.root, 'build/remediation/retained/AUDIT_REPORT.md').read_bytes()
        self.check('original audit retained', hashlib.sha256(original).hexdigest()
                   == baseline['files']['audit/AUDIT_REPORT.md'])
        self.check('audit report append only', local(self.root, 'audit/AUDIT_REPORT.md').read_bytes().startswith(original))

    def historical(self):
        saved = self.read('audit/remediation/historical-identities.json')
        for name, identity in saved.items():
            if not name.startswith('results/derived/'):
                self.identity(name, identity)
        frozen = json.loads(local(self.root, 'results/p7/p6-figure-extension-baseline.json').read_text())
        for name, identity in frozen.items():
            if name.startswith('results/derived/'):
                self.identity(name, identity)
        self.identity('results/p7/baseline-p6-figures.json', frozen['results/figures/p6-figures.json'])
        p8 = json.loads(local(self.root, 'results/p8/acceptance-evidence.json').read_text())
        for name, identity in p8['figure_regeneration']['outputs'].items():
            self.identity(name, identity)
        binaries = self.read('audit/remediation/historical-binaries.json')
        self.check('19 retained historical binaries', len(binaries) == 19)
        for item in binaries.values():
            self.identity(item['backup'], item['before_sha256'])
            self.check('historical binary matches frozen identity', item['before_sha256'] == item['frozen_sha256'])
        reconciliation = self.read('audit/remediation/reconcile-baseline.json')
        semantics = self.read('audit/remediation/reconcile-semantic.json')
        self.check('exact frozen reconstruction', reconciliation['status'] == 'passed'
                   and len(reconciliation['files']) == 4
                   and all(item['matches_frozen'] for item in reconciliation['files'].values()))
        self.check('only noise annotations changed', semantics['status'] == 'passed'
                   and semantics['all_other_summary_fields_identical'] is True
                   and all(row['other_fields_identical'] for row in semantics['csv'].values()))
        for name, old in saved.items():
            if name.startswith('results/derived/'):
                self.identity('build/remediation/retained/derived/' + Path(name).name, old)
        raw = self.read('audit/remediation/tools/frozen-p6-measurements.json')
        self.check('frozen raw measurement verification', raw['status'] == 'passed'
                   and raw['files_verified'] == raw['original_files'] == 5364
                   and raw['current_bytes_verified'] == raw['original_bytes'] == 4105957437
                   and raw['changed_files'] == [])
        original_hashes = self.read(raw['original_identity_manifest'])
        # Recheck the original raw-file identities rather than trusting the saved summary.
        self.check('complete original measurement inventory', len(original_hashes['files']) == 5364)
        self.check('authoritative raw inventory path', raw['original_identity_manifest'] ==
                   'results/p6/auditor-t5-compatibility/measurement-files-before.json')
        self.check('unique raw measurement coverage',
                   len({row['path'] for row in original_hashes['files']}) == 5364
                   and sum(row['bytes'] for row in original_hashes['files']) == 4105957437
                   and all(row['path'].startswith('results/raw/P6/') for row in original_hashes['files']))
        for identity in original_hashes['files']:
            self.identity(identity['path'], identity)

    def executed(self):
        checks = self.manifest['executed_checks']
        required = {f'{preset}-{step}' for preset in PRESETS for step in ('configure', 'build', 'ctest')}
        required |= {'python-root', 'python-from-py', 'experiment-auditor', 'pip-check'}
        self.check('complete executed check matrix', set(checks) == required)
        self.check('distinct command records', len({item['record'] for item in checks.values()}) == len(checks))
        for label in sorted(required):
            self.section(label, lambda label=label: self.executed_one(label, checks[label]))

    def executed_one(self, label, reference):
        record = self.read(reference['record'])
        working_directory = self.root / 'py' if label == 'python-from-py' else self.root
        self.check(f'{label}:exit', record['status'] == 'passed' and type(record['exit_code']) is int
                   and record['exit_code'] == 0 and record['argv']
                   and Path(record['cwd']).resolve() == working_directory.resolve())
        self.check(f'{label}:command', record['argv'] == self.expected_command(label, reference))
        self.identity(record['log'], record['log_sha256'])
        group = 'cpp' if any(label.endswith('-' + step) for step in ('configure', 'build', 'ctest')) else 'python'
        self.check(f'{label}:unchanged tested inputs',
                   record['input_sets_before'][group] == record['input_sets_after'][group]
                   == self.current_inputs[group])
        if label.endswith('-ctest') or label.startswith('python-'):
            if label.endswith('-ctest'):
                preset = label.removesuffix('-ctest')
                argv = record['argv']
                self.check(f'{label}:correct preset', argv[0] == 'ctest' and '--preset' in argv
                           and argv[argv.index('--preset') + 1] == preset)
                if preset in ('asan-ubsan', 'fuzz'):
                    self.check(f'{label}:sanitizers enabled',
                               record['environment']['ASAN_OPTIONS'] == 'detect_leaks=1:abort_on_error=1'
                               and record['environment']['UBSAN_OPTIONS'] == 'print_stacktrace=1:halt_on_error=1')
            minimum = 205 if label.endswith('-ctest') else (242 if label == 'python-root' else 225)
            self.identity(reference['junit'], self.evidence[reference['junit']])
            count = junit_counts(local(self.root, reference['junit']), minimum)
            self.check(f'{label}:executed tests', count == reference['tests'], {'tests': count})
        if label.endswith('-configure'):
            preset = label.removesuffix('-configure')
            cache = local(self.root, f'build/{preset}/CMakeCache.txt').read_text()
            self.check(f'{label}:pinned GoogleTest provider',
                       'TIPLOG_ALLOW_SYSTEM_GTEST:BOOL=OFF' in cache
                       and 'TIPLOG_GTEST_PROVIDER:INTERNAL=FetchContent v1.17.0' in cache
                       and 'tiplog GoogleTest provider: FetchContent v1.17.0'
                       in local(self.root, record['log']).read_text())

    def expected_command(self, label, reference):
        for preset in PRESETS:
            if label == f'{preset}-configure':
                return ['cmake', '--preset', preset]
            if label == f'{preset}-build':
                return ['cmake', '--build', '--preset', preset, '--parallel', '2']
            if label == f'{preset}-ctest':
                return ['ctest', '--preset', preset, '--output-on-failure', '--no-tests=error',
                        '--output-junit', str(self.root / reference['junit'])]
        if label == 'python-root':
            return ['.venv/bin/python', '-m', 'pytest', '-c', 'py/pytest.ini', 'py/tests',
                    'tests/scripts', '-q', '--junitxml=' + reference['junit']]
        if label == 'python-from-py':
            return [str(self.root / '.venv/bin/python'), '-m', 'pytest', '-q',
                    '--junitxml=' + str(self.root / reference['junit'])]
        if label == 'experiment-auditor':
            return ['.venv/bin/python', 'scripts/check_p6_experiments.py', '--self-test']
        if label == 'pip-check':
            return ['.venv/bin/python', '-m', 'pip', 'check']
        raise ValueError(f'unknown executed check: {label}')

    def functional(self):
        summary = self.read('audit/remediation/core/final-validation/summary.json')
        runner = self.read('audit/remediation/core/final-validation/runner-identity.json')
        self.identity(runner['path'], runner['sha256'])
        self.check('bounded functional concurrency', summary['maximum_tested_children'] == 2
                   and runner['maximum_tested_children'] == 2 and summary['performance_claim'] is False)
        self.check('functional source stability', summary['passed'] is True and summary['source_unchanged'] is True)
        self.check('complete functional jobs', len(summary['jobs']) == 21
                   and len({job['id'] for job in summary['jobs']}) == 21)
        for preset, seeds in (('release', 1000), ('asan-ubsan', 200)):
            jobs = [job for job in summary['jobs'] if job.get('preset') == preset]
            self.check(f'{preset}:all differential pairs', {(job['mode'], job['kernel']) for job in jobs} == PAIRS)
            self.check(f'{preset}:full independent-oracle operations',
                       len(jobs) == 9 and all(job['seeds'] == seeds and job['passed'] is True
                       and job['exit_status'] == 0 and job['result']['operations'] == seeds * 10000 for job in jobs))
            digests = {job['result']['digest_fnv1a64'] for job in jobs}
            self.check(f'{preset}:mode-independent output', len(digests) == 1)
        fuzzers = [job for job in summary['jobs'] if job['kind'] == 'fuzz']
        self.check('three 10000-run fuzzer smokes',
                   {job['id'] for job in fuzzers} == {'fuzz_trace_reader', 'fuzz_itch_walker', 'fuzz_engine_ops'}
                   and all(job['passed'] is True and job['exit_status'] == 0
                           and 'stat::number_of_executed_units: 10000' in job['final_stats'] for job in fuzzers))
        for job in summary['jobs']:
            self.identity(job['command'][0], job['binary_sha256_before'])
            self.check(f"{job['id']}:binary unchanged", job['binary_unchanged'] is True
                       and job['binary_sha256_before'] == job['binary_sha256_after'])
            directory = f"audit/remediation/core/final-validation/{job['id']}/"
            self.check(f"{job['id']}:saved result bound", self.read(directory + 'result.json') == job)
            if job['kind'] == 'differential':
                self.check(f"{job['id']}:raw output bound", self.read(directory + 'stdout.log') == job['result'])
                self.check(f"{job['id']}:oracle binary", job['command'][0] ==
                           str(self.root / 'build' / job['preset'] / 'tiplog_differential'))
                self.check(f"{job['id']}:oracle command", job['command'][1:] == [
                    '--seed-base', '1', '--seeds', str(job['seeds']), '--operations', '10000',
                    '--mode', job['mode'], '--kernel', job['kernel']])
                self.check(f"{job['id']}:oracle result configuration", job['result']['mode'] == job['mode']
                           and job['result']['kernel'] == job['kernel'] and job['result']['seed_base'] == 1
                           and job['result']['operations_per_seed'] == 10000
                           and job['result']['seeds'] == job['seeds'])
            else:
                base = self.root / 'audit/remediation/core/final-validation'
                self.check(f"{job['id']}:fuzzer command", job['command'] == [
                    str(self.root / 'build/fuzz' / job['id']), str(base / (job['id'] + '-corpus')),
                    '-runs=10000', '-seed=1', '-max_len=65536', '-detect_leaks=1',
                    '-print_final_stats=1', '-artifact_prefix=' + str(base / (job['id'] + '-artifacts')) + '/'])
                self.check(f"{job['id']}:fuzzer environment", job['environment'] ==
                           ({'TIPLOG_FUZZ_MODE': 'all'} if job['id'] == 'fuzz_engine_ops' else {}))
                stderr = directory + 'stderr.log'
                self.identity(stderr, self.evidence[stderr])
                stats = [line for line in local(self.root, stderr).read_text().splitlines()
                         if line.startswith('stat::')]
                self.check(f"{job['id']}:raw smoke statistics bound", stats == job['final_stats'])
            self.check(f"{job['id']}:sanitizers enabled", job['sanitizer_environment'] == {
                'ASAN_OPTIONS': 'detect_leaks=1:abort_on_error=1',
                'UBSAN_OPTIONS': 'print_stacktrace=1:halt_on_error=1'})
        source_before = self.read('audit/remediation/core/final-validation/source-hashes-before.json')
        source_after = self.read('audit/remediation/core/final-validation/source-hashes-after.json')
        self.check('functional source snapshots agree', source_before == source_after)
        required_sources = {name for name in source_inventory(self.root)
                            if (name.startswith(('src/', 'tools/', 'tests/', 'cmake/'))
                                and Path(name).suffix in {'.cpp', '.hpp', '.h', '.c', '.cmake'})
                            or name in {'CMakeLists.txt', 'CMakePresets.json'}}
        self.check('functional source coverage complete', bool(required_sources)
                   and required_sources <= set(source_before))
        for name, sha in source_after.items():
            self.identity(name, sha)
        mutants = self.read('audit/remediation/core/mutation-summary.json')
        self.check('three vacuous checkers killed', len(mutants) == 3
                   and {row['no_op_checker'] for row in mutants} == {'ring', 'index', 'engine'}
                   and all(row['negative_control_killed'] is True and row['exit_code'] != 0 for row in mutants))
        budgets = self.read('audit/remediation/tools/frozen-budget-preflight.json')
        self.check('all frozen layouts fit budgets', len(budgets['batches']) == 32
                   and len(budgets['global_curve_batches']) == 24
                   and budgets['default_budget_checks']['current']['all_frozen_batches_fit'] is True)
        inputs = self.read('results/p7/input-manifest.json')
        self.check('frozen preflight input coverage', {row['path'] for row in budgets['batches']}
                   == {row['path'] for row in inputs['batches']})
        for row in inputs['batches']:
            self.identity(row['path'], row)
        self.check('declared budget header', budgets['budget_source_header'] == 'tools/tiplog_layout/input_budget.hpp')
        self.identity(budgets['budget_source_header'], budgets['budget_source_header_sha256'])
        limits = budgets['default_budget_checks']['current']
        self.check('case input bounds satisfied', all(
            row['bytes'] <= limits['max_input_bytes']
            and row['aggregate_preparation_work_bound'] <= limits['max_prepare_work']
            and row['maximum_case_membership_upper_bound'] <= limits['max_prepared_entries']
            for row in budgets['batches']))
        self.check('curve input bounds satisfied', all(
            row['bytes'] <= limits['max_input_bytes'] and row['aggregate_entries'] <= limits['max_curve_entries']
            for row in budgets['global_curve_batches']))
        for row in budgets['global_curve_batches']:
            self.identity(row['path'], row)
        layout = self.read('audit/remediation/tools/layout-closeout.json')
        self.check('fresh layout oracle and worked example', layout['status'] == 'passed'
                   and len(layout['cc5']) == len(layout['worked_example']) == 2
                   and {row['preset'] for row in layout['cc5']} == {'release', 'asan-ubsan'}
                   and {row['preset'] for row in layout['worked_example']} == {'release', 'asan-ubsan'}
                   and all(row['exit_code'] == 0 and row['completed_instances'] == 10000
                           and row['matches_historical_cc5_json'] is True for row in layout['cc5'])
                   and all(row['exit_code'] == 0 and row['json_identical_to_snapshot'] is True
                           for row in layout['worked_example']))
        for row in layout['cc5'] + layout['worked_example']:
            self.identity(row['command'][0], row['binary_sha256'])
            self.identity(row['output'], row['output_sha256'])
            result = self.read(row['output'])
            if row in layout['cc5']:
                self.check(f"{row['preset']}:CC5 oracle agrees", result['status'] == 'passed'
                           and result['completed_instances'] == 10000 and result['mismatches'] == 0
                           and result == self.read('results/p7/cc5-release.json'))
            else:
                self.identity(row['snapshot'], row['snapshot_sha256'])
                self.check(f"{row['preset']}:frozen worked example agrees", result == self.read(row['snapshot'])
                           and local(self.root, row['output']).read_bytes() == local(self.root, row['snapshot']).read_bytes())
        quiescence = self.read('audit/remediation/historical-quiescence.json')
        self.check('accepted-attempt historical quiescence', quiescence['status'] == 'passed'
                   and len(quiescence['rounds']) == 11 and not quiescence['failures'])

    def dependencies(self):
        report = self.read('audit/remediation/pip-audit.json')
        self.check('dependency advisories clean', len(report['dependencies']) == 15
                   and all(row.get('vulns') == [] for row in report['dependencies'])
                   and any(row['name'] == 'pytest' and row['version'] == '9.0.3' for row in report['dependencies']))
        pins = set(re.findall(r'^([\w-]+)==([^\s]+)',
                              local(self.root, 'py/requirements.txt').read_text(), re.M))
        normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
        self.check('advisory report covers exact pins', {(normalize(name), version) for name, version in pins}
                   == {(normalize(row['name']), row['version']) for row in report['dependencies']})

    def run(self):
        for label, action in (('sources', self.sources), ('scope', self.scope),
                              ('historical', self.historical), ('executed checks', self.executed),
                              ('functional checks', self.functional), ('dependencies', self.dependencies)):
            self.section(label, action)
        # Bind auxiliary notes, logs, commands and snapshots cited by the findings too.
        for name, identity in self.evidence.items():
            self.section(f'evidence:{name}', lambda name=name, identity=identity: self.identity(name, identity))
        failures = [item for item in self.checks if item['status'] == 'failed']
        return {'schema': 'tiplog-remediation-check-v1', 'status': 'failed' if failures else 'passed',
                'checked_utc': datetime.now(timezone.utc).isoformat(),
                'checks': self.checks, 'failures': failures,
                'scope': 'Current audit fixes; P1-P8 remain historical. F-01 is deferred.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'audit/remediation/acceptance.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'audit/remediation/checks.json')
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text())
        result = Audit(manifest).run()
        result['manifest_sha256'] = digest(args.manifest)
    except (OSError, ValueError, TypeError) as error:
        result = {'schema': 'tiplog-remediation-check-v1', 'status': 'failed',
                  'checks': [], 'failures': [{'check': 'manifest readable', 'details': str(error)}]}
    if args.output.resolve() == args.manifest.resolve():
        parser.error('output must differ from the acceptance manifest')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']),
                      'failures': len(result['failures']), 'output': str(args.output)}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
