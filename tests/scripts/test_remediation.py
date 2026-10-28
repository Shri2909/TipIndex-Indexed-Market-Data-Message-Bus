"""Negative controls for current remediation evidence acceptance."""
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('remediation_checker', ROOT / 'scripts/check_remediation.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def saved_check(tmp_path, label='release-ctest'):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/core.cpp').write_text('int core() { return 1; }\n')
    reference = {'record': 'audit/check.json', 'junit': 'audit/tests.xml', 'tests': 205}
    report = tmp_path / reference['junit']
    report.parent.mkdir()
    suite = ET.Element('testsuite', tests='205', failures='0', errors='0', skipped='0')
    for number in range(205):
        ET.SubElement(suite, 'testcase', name=f'test_{number}', classname='current')
    ET.ElementTree(suite).write(report)
    log = tmp_path / 'audit/check.log'
    log.write_text('205 checks passed\n')
    audit = checker.Audit({'evidence': {}}, tmp_path)
    inputs = checker.input_sets(tmp_path)
    record = {'status': 'passed', 'exit_code': 0, 'cwd': str(tmp_path),
              'argv': audit.expected_command(label, reference),
              'log': 'audit/check.log', 'log_sha256': checker.digest(log),
              'input_sets_before': inputs, 'input_sets_after': inputs,
              'environment': {'ASAN_OPTIONS': 'detect_leaks=1:abort_on_error=1',
                              'UBSAN_OPTIONS': 'print_stacktrace=1:halt_on_error=1'}}
    save(tmp_path / reference['record'], record)
    for name in (reference['record'], reference['junit'], 'audit/check.log'):
        audit.evidence[name] = checker.digest(tmp_path / name)
    audit.current_inputs = inputs
    return audit, reference, record


def run(audit, reference, label='release-ctest'):
    audit.section(label, lambda: audit.executed_one(label, reference))
    return [row for row in audit.checks if row['status'] == 'failed']


def replace_record(audit, reference, record):
    path = audit.root / reference['record']
    save(path, record)
    audit.evidence[reference['record']] = checker.digest(path)


def test_bound_current_execution_passes(tmp_path):
    audit, reference, _ = saved_check(tmp_path)
    assert run(audit, reference) == []


def test_log_tamper_rejects_even_when_saved_exit_is_success(tmp_path):
    audit, reference, _ = saved_check(tmp_path)
    (tmp_path / 'audit/check.log').write_text('different command\n')
    assert run(audit, reference)


@pytest.mark.parametrize('command', [['true'], ['ctest', '--preset', 'debug'],
                                    ['ctest', '--preset', 'release', '--output-junit', '/wrong.xml']])
def test_wrong_command_cannot_replace_the_required_check(tmp_path, command):
    audit, reference, record = saved_check(tmp_path)
    record['argv'] = command
    replace_record(audit, reference, record)
    assert any(row['check'].endswith(':command') for row in run(audit, reference))


def test_stale_tested_sources_reject(tmp_path):
    audit, reference, _ = saved_check(tmp_path)
    (tmp_path / 'src/core.cpp').write_text('int core() { return 2; }\n')
    audit.current_inputs = checker.input_sets(tmp_path)
    assert any('tested inputs' in row['check'] for row in run(audit, reference))


def test_sources_changed_during_execution_reject(tmp_path):
    audit, reference, record = saved_check(tmp_path)
    record['input_sets_after'] = dict(record['input_sets_after'], cpp='0' * 64)
    replace_record(audit, reference, record)
    assert run(audit, reference)


def test_sanitizer_disable_cannot_pass_as_sanitized(tmp_path):
    audit, reference, record = saved_check(tmp_path, 'asan-ubsan-ctest')
    record['environment']['ASAN_OPTIONS'] = 'detect_leaks=0'
    replace_record(audit, reference, record)
    assert any('sanitizers' in row['check'] for row in run(audit, reference, 'asan-ubsan-ctest'))


@pytest.mark.parametrize('tag', ['failure', 'error', 'skipped'])
def test_junit_case_failure_cannot_hide_behind_zero_suite_counts(tmp_path, tag):
    audit, reference, _ = saved_check(tmp_path)
    path = tmp_path / reference['junit']
    document = ET.parse(path)
    ET.SubElement(document.getroot()[0], tag)
    document.write(path)
    audit.evidence[reference['junit']] = checker.digest(path)
    assert run(audit, reference)


def test_empty_and_duplicate_junit_cannot_meet_minimum(tmp_path):
    path = tmp_path / 'empty.xml'
    path.write_text('<testsuite tests="205"/>')
    with pytest.raises(ValueError, match='missing or duplicate'):
        checker.junit_counts(path, 205)
    path.write_text('<testsuite>' + '<testcase name="same"/>' * 205 + '</testsuite>')
    with pytest.raises(ValueError, match='missing or duplicate'):
        checker.junit_counts(path, 205)


def test_new_unreviewed_source_is_detected(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/core.cpp').write_text('int core();')
    manifest = {'sources': checker.source_inventory(tmp_path),
                'input_sets': checker.input_sets(tmp_path)}
    (tmp_path / 'src/extra.cpp').write_text('int extra();')
    audit = checker.Audit(manifest, tmp_path)
    audit.sources()
    assert any(row['status'] == 'failed' for row in audit.checks)


def test_evidence_outside_workspace_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='escapes'):
        checker.local(tmp_path, '../other-source.cpp')


def test_missing_prerequisites_fail_closed(tmp_path):
    result = checker.Audit({'schema': checker.SCHEMA}, tmp_path).run()
    assert result['status'] == 'failed'
    assert result['failures']


@pytest.mark.parametrize('tamper', [False, True])
def test_advisory_coverage_uses_package_identity_and_exact_version(tmp_path, tamper):
    packages = [('pytest', '9.0.3'), ('pygments', '2.21.0')]
    packages += [(f'package-{number}', '1.0') for number in range(13)]
    report = {'dependencies': [{'name': name, 'version': version, 'vulns': []}
                               for name, version in packages]}
    name = 'audit/remediation/pip-audit.json'
    save(tmp_path / name, report)
    requirements = tmp_path / 'py/requirements.txt'
    requirements.parent.mkdir()
    requirements.write_text('\n'.join(f'{name.upper()}=={version}' for name, version in packages)
                            .replace('PYTEST==9.0.3', 'PYTEST==9.0.2' if tamper else 'PYTEST==9.0.3'))
    audit = checker.Audit({'evidence': {name: checker.digest(tmp_path / name)}}, tmp_path)
    audit.dependencies()
    assert any(row['status'] == 'failed' for row in audit.checks) is tamper
