"""Evidence-level negative controls for the independent F-01 closeout checker."""
import copy
import importlib.util
import json
import shlex
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('f01_checker', ROOT / 'scripts/check_f01.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def write(audit, name, value, *, text=False):
    path = audit.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if text else json.dumps(value))
    audit.evidence[name] = {'sha256': checker.digest(path), 'bytes': path.stat().st_size}
    return path


def fixture(tmp_path):
    path = tmp_path / 'src/core.cpp'
    path.parent.mkdir()
    path.write_text('int core() { return 1; }\n')
    (tmp_path/'CMakePresets.json').write_text((ROOT/'CMakePresets.json').read_text())
    return checker.Audit({'evidence': {}}, tmp_path)


def command(audit, argv, *, preset='release', log='successful command\n', label=None):
    record = {
        'status': 'passed', 'exit_code': 0, 'cwd': str(audit.root),
        'argv': argv, 'elapsed_seconds': 0.1,
        'input_sets_before': audit.current_inputs.copy(),
        'input_sets_after': audit.current_inputs.copy(),
        'environment': {'ASAN_OPTIONS': 'detect_leaks=1:abort_on_error=1',
                        'UBSAN_OPTIONS': 'print_stacktrace=1:halt_on_error=1',
                        **{name: None for name in checker.FULL_SUITE_SELECTION_ENV},
                        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
        'log': 'results/f01/' + (label or 'check') + '.log',
    }
    executed_preset = None
    if argv[0] == 'ctest' and '--preset' in argv:
        executed_preset = argv[argv.index('--preset')+1]
    elif argv[0].startswith('build/'):
        executed_preset = Path(argv[0]).parts[1]
    elif len(argv) > 1 and argv[1] == 'scripts/run_f01_fuzz.py':
        executed_preset = 'fuzz'
    if executed_preset:
        snapshot = source_bound_build(audit, executed_preset)
        record['build_artifacts_before'] = copy.deepcopy(snapshot)
        record['build_artifacts_after'] = copy.deepcopy(snapshot)
    path = write(audit, record['log'], log, text=True)
    record['log_sha256'] = checker.digest(path)
    name = 'results/f01/' + (label + '.record' if label else 'record') + '.json'
    write(audit, name, record)
    return name, record


def source_bound_build(audit, preset):
    builds = audit.manifest.setdefault('builds', {})
    if preset in builds:
        return audit.read(builds[preset])['build_provenance']
    directory = audit.root/'build'/preset
    directory.mkdir(parents=True, exist_ok=True)
    compiler = audit.root/'compiler'
    compiler.write_text('compiler identity')
    presets = json.loads((audit.root/'CMakePresets.json').read_text())['configurePresets']
    variables = {}
    for item in presets:
        if item['name'] in ('base', preset):
            variables.update(item.get('cacheVariables', {}))
    variables.update(CMAKE_HOME_DIRECTORY=str(audit.root), CMAKE_CACHEFILE_DIR=str(directory),
                     CMAKE_CXX_COMPILER=str(compiler))
    (directory/'CMakeCache.txt').write_text(
        ''.join(f'{key}:STRING={value}\n' for key, value in variables.items()))
    flags = variables['CMAKE_CXX_FLAGS_'+variables['CMAKE_BUILD_TYPE'].upper()]
    (directory/'compile_commands.json').write_text(json.dumps([
        dict(directory=str(directory), file=str(audit.root/'src/core.cpp'),
             arguments=[str(compiler), *shlex.split(flags), '-std=c++20', '-c', 'core.cpp'])]))
    detection = directory/'CMakeFiles/4.4.0/CMakeCXXCompiler.cmake'
    detection.parent.mkdir(parents=True, exist_ok=True)
    compiler_id = 'Clang' if preset in ('asan-ubsan', 'fuzz') else 'GNU'
    detection.write_text(f'set(CMAKE_CXX_COMPILER "{compiler}")\n'
                         f'set(CMAKE_CXX_COMPILER_ID "{compiler_id}")\nset(CMAKE_CXX_COMPILER_VERSION "15.2.0")\n')
    names = checker.FUZZERS if preset == 'fuzz' else {
        'tiplog_test', 'tiplog_differential', 'tiplog_poll_differential', 'tiplog_poll_bench'}
    for name in names:
        path = directory/name
        if not path.exists():
            path.write_text('retained executable placeholder')
        path.chmod(0o755)
    snapshot = checker._BUILD.capture_build(audit.root, preset, audit.current_inputs['cpp'])
    for name, identity in snapshot['artifacts'].items():
        audit.evidence[name] = identity
    name, record = command(audit, ['cmake', '--build', '--preset', preset, '--parallel', '2'], label='build-'+preset)
    record.update(build_execution={'preset': preset, 'kind': 'build', 'full_build': True},
                  build_provenance=snapshot, build_artifacts_after=snapshot)
    write(audit, name, record)
    builds[preset] = name
    return snapshot


def junit(audit, name, *, old=205, contract=23, differential=1):
    suite = ET.Element('testsuite', failures='0', errors='0', skipped='0')
    for prefix, count in (('legacy.', old), ('poll_budget.', contract),
                          ('poll_differential.', differential)):
        for index in range(count):
            ET.SubElement(suite, 'testcase', name=f'{prefix}case{index}', classname=prefix)
    return write(audit, name, ET.tostring(suite, encoding='unicode'), text=True)


def ctest(audit, *, preset='release', old=205, contract=23, differential=1):
    name = 'results/f01/tests.xml'
    junit(audit, name, old=old, contract=contract, differential=differential)
    record_name, record = command(audit, ['ctest', '--preset', preset, '-j2',
                                         '--output-junit', str(audit.root / name)])
    return {'record': record_name, 'junit': name}, record


def test_current_full_ctest_evidence_passes(tmp_path):
    audit = fixture(tmp_path)
    reference, _ = ctest(audit)
    assert audit.ctest_one('release', reference) == {
        'tests': 229, 'poll_budget': 23, 'poll_differential': 1}


def python_suite(audit):
    name = 'results/f01/python.xml'
    junit(audit, name, old=259, contract=0, differential=0)
    record_name, record = command(audit, [
        '.venv/bin/python', '-m', 'pytest', '-c', 'py/pytest.ini', 'py/tests',
        'tests/scripts', '-q', '--junitxml='+name], label='python')
    reference = {'record': record_name, 'junit': name}
    audit.manifest['validations'] = {'python': reference}
    return reference, record


@pytest.mark.parametrize('suite', ['ctest', 'python'])
def test_full_suite_accepts_explicit_empty_selection_controls(tmp_path, suite):
    audit = fixture(tmp_path)
    reference, record = ctest(audit) if suite == 'ctest' else python_suite(audit)
    record['environment'].update({name: '' for name in checker.FULL_SUITE_SELECTION_ENV})
    write(audit, reference['record'], record)
    if suite == 'ctest': assert audit.ctest_one('release', reference)['tests'] == 229
    else: assert audit.python()['tests'] == 259


@pytest.mark.parametrize('suite', ['ctest', 'python'])
@pytest.mark.parametrize('name,value', [
    ('GTEST_FILTER', '-PollBudget.TailExpiryAfterFailedAppendReportsActuallyDeliveredPrefix'),
    ('GTEST_TOTAL_SHARDS', '999999'), ('GTEST_SHARD_INDEX', '999998'),
    ('GTEST_REPEAT', '0'), ('TESTBRIDGE_TEST_ONLY', '-PollBudget.TailExpiryAfterFailedAppendReportsActuallyDeliveredPrefix'),
    ('CTEST_TESTS_TO_RUN', '0,0,1'), ('PYTEST_ADDOPTS', '-k not_the_new_regression'),
    ('PYTEST_PLUGINS', 'injected_plugin'), ('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '0')])
def test_active_environment_cannot_claim_a_complete_suite(tmp_path, suite, name, value):
    audit = fixture(tmp_path)
    reference, record = ctest(audit) if suite == 'ctest' else python_suite(audit)
    # Keep the full-looking JUnit and all build/source/log identities intact.
    record['environment'][name] = value
    write(audit, reference['record'], record)
    with pytest.raises(ValueError, match='full suite'):
        audit.ctest_one('release', reference) if suite == 'ctest' else audit.python()


@pytest.mark.parametrize('suite', ['ctest', 'python'])
@pytest.mark.parametrize('name', [*checker.FULL_SUITE_SELECTION_ENV, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'])
def test_unrecorded_environment_cannot_claim_a_complete_suite(tmp_path, suite, name):
    audit = fixture(tmp_path)
    reference, record = ctest(audit) if suite == 'ctest' else python_suite(audit)
    del record['environment'][name]
    write(audit, reference['record'], record)
    with pytest.raises(ValueError, match='full suite'):
        audit.ctest_one('release', reference) if suite == 'ctest' else audit.python()


@pytest.mark.parametrize('damage', ['missing_build', 'changed_binary', 'changed_recorded_binary', 'partial_build'])
def test_current_source_hashes_cannot_bless_stale_or_unbound_execution(tmp_path, damage):
    audit = fixture(tmp_path)
    reference, record = ctest(audit)
    build_name = audit.manifest['builds']['release']
    if damage == 'missing_build':
        audit.manifest['builds'] = {}
    elif damage == 'changed_binary':
        (tmp_path/'build/release/tiplog_test').write_text('stale replacement')
    elif damage == 'changed_recorded_binary':
        record['build_artifacts_before']['artifacts']['build/release/tiplog_test']['sha256'] = 'f'*64
        write(audit, reference['record'], record)
    else:
        build = audit.read(build_name)
        build['argv'] += ['--target', 'tiplog_test']
        write(audit, build_name, build)
    with pytest.raises(ValueError, match='build|artifacts|complete preset'):
        audit.ctest_one('release', reference)


@pytest.mark.parametrize('change', ['old', 'contract', 'model'])
def test_total_test_count_cannot_hide_missing_required_suite(tmp_path, change):
    audit = fixture(tmp_path)
    counts = {'old': (204, 24, 1), 'contract': (206, 22, 1), 'model': (206, 23, 0)}[change]
    reference, _ = ctest(audit, old=counts[0], contract=counts[1], differential=counts[2])
    with pytest.raises(ValueError, match='omits'):
        audit.ctest_one('release', reference)


@pytest.mark.parametrize('extra', [['-R', 'poll'], ['--rerun-failed'], ['--show-only']])
def test_filtered_ctest_cannot_claim_full_matrix(tmp_path, extra):
    audit = fixture(tmp_path)
    reference, record = ctest(audit)
    record['argv'] += extra
    write(audit, reference['record'], record)
    with pytest.raises(ValueError, match='filtered or unknown'):
        audit.ctest_one('release', reference)


def test_junit_must_be_the_executed_destination(tmp_path):
    audit = fixture(tmp_path)
    reference, record = ctest(audit)
    record['argv'][-1] = str(audit.root / 'different.xml')
    write(audit, reference['record'], record)
    with pytest.raises(ValueError, match='destination'):
        audit.ctest_one('release', reference)


def test_sanitizer_evidence_requires_leak_detection(tmp_path):
    audit = fixture(tmp_path)
    reference, record = ctest(audit, preset='asan-ubsan')
    record['environment']['ASAN_OPTIONS'] = 'detect_leaks=0:abort_on_error=1'
    write(audit, reference['record'], record)
    with pytest.raises(ValueError, match='sanitizer disabled'):
        audit.ctest_one('asan-ubsan', reference)


def test_rebound_log_cannot_override_runner_log_hash(tmp_path):
    audit = fixture(tmp_path)
    name, record = command(audit, ['true'])
    write(audit, record['log'], 'different output\n', text=True)
    with pytest.raises(ValueError, match='nested log/file hash'):
        audit.runner(name)


@pytest.mark.parametrize('update', [{'status': 'running'}, {'exit_code': False}, {'exit_code': -11}])
def test_unfinished_bool_or_crashed_command_is_not_success(tmp_path, update):
    audit = fixture(tmp_path)
    name, record = command(audit, ['true'])
    record.update(update)
    write(audit, name, record)
    with pytest.raises(ValueError, match='command'):
        audit.runner(name)


def test_sanitizer_diagnostic_cannot_hide_behind_exit_zero(tmp_path):
    audit = fixture(tmp_path)
    name, _ = command(audit, ['true'], log='ERROR: LeakSanitizer: detected memory leaks\n')
    with pytest.raises(ValueError, match='sanitizer failure'):
        audit.runner(name)


def test_old_inputs_allowed_only_for_explicit_compatible_differential(tmp_path):
    audit = fixture(tmp_path)
    name, record = command(audit, ['true'])
    previous = 'a' * 64
    audit.allowed_differential_cpp.add(previous)
    record['input_sets_before']['cpp'] = previous
    write(audit, name, record)
    with pytest.raises(ValueError, match='executed cpp'):
        audit.runner(name)
    assert audit.runner(name, compatible=True)[0]['status'] == 'passed'


def frozen(audit):
    test = audit.root / 'tests/unit/poll_budget_test.cpp'
    test.parent.mkdir(parents=True)
    test.write_text('current allocator hook\n')
    audit.current_inputs = checker.input_sets(audit.root)
    protocol = write(audit, 'results/f01/protocol.json', {'scope': 'traversal only'})
    inventory = checker.source_inventory(audit.root)
    current = {'schema': 'tiplog-f01-source-freeze-v1',
               'compiled_sources': checker.compiled_sources(inventory),
               'cpp_input_set': audit.current_inputs['cpp'], 'protocol_sha256': checker.digest(protocol)}
    name = 'results/f01/source-freeze-final.json'
    write(audit, name, current)
    audit.manifest.update(sources=inventory, input_sets=audit.current_inputs,
                          source_freeze=name)
    return current


def test_exact_current_source_inventory_and_freeze_pass(tmp_path):
    audit = fixture(tmp_path)
    frozen(audit)
    assert audit.sources()['compatible_differential_cpp_sets'] == 1


def test_new_unreviewed_source_rejects(tmp_path):
    audit = fixture(tmp_path)
    frozen(audit)
    (tmp_path / 'src/new.cpp').write_text('int added;\n')
    with pytest.raises(ValueError, match='inventory'):
        audit.sources()


@pytest.mark.parametrize('production_change', [False, True])
def test_compatible_freeze_only_permits_the_allocator_test_change(tmp_path, production_change):
    audit = fixture(tmp_path)
    earlier = copy.deepcopy(frozen(audit))
    earlier['compiled_sources']['tests/unit/poll_budget_test.cpp'] = 'b' * 64
    if production_change:
        earlier['compiled_sources']['src/core.cpp'] = 'c' * 64
    earlier['cpp_input_set'] = checker.mapping_hash(earlier['compiled_sources'])
    name = 'results/f01/source-freeze.json'
    write(audit, name, earlier)
    audit.manifest['compatible_cpp_freezes'] = [name]
    if production_change:
        with pytest.raises(ValueError, match='production/campaign'):
            audit.sources()
    else:
        assert audit.sources()['compatible_differential_cpp_sets'] == 2


def normalization(audit):
    before = {'repetition': 0, 'drain_elapsed_ns': 10, 'poll_work': {'records_fetched': 3}}
    after = dict(before, repetition=1)
    original, derived = 'results/f01/original.jsonl', 'results/f01/derived.jsonl'
    first = write(audit, original, json.dumps(before) + '\n', text=True)
    second = write(audit, derived, json.dumps(after) + '\n', text=True)
    entry = {'input': original, 'output': derived, 'input_sha256': checker.digest(first),
             'output_sha256': checker.digest(second), 'tool_repetition': 0,
             'process_repetition': 1, 'rows': 1, 'record': 'results/f01/direct-record.json'}
    return {'files': [entry]}, {'original_raw': [original], 'raw': [derived]}, after


def test_repetition_only_normalization_passes(tmp_path):
    audit = fixture(tmp_path)
    value, reference, _ = normalization(audit)
    assert list(audit.check_normalization(value, reference)) == reference['original_raw']


@pytest.mark.parametrize('change', ['timing', 'work', 'integer_to_float', 'bool_repetition'])
def test_normalization_cannot_rewrite_measured_values_even_with_new_hashes(tmp_path, change):
    audit = fixture(tmp_path)
    value, reference, after = normalization(audit)
    if change == 'timing':
        after['drain_elapsed_ns'] = 1
    elif change == 'work':
        after['poll_work']['records_fetched'] = 2
    elif change == 'integer_to_float':
        after['drain_elapsed_ns'] = 10.0
    else:
        after['repetition'] = True
    path = write(audit, reference['raw'][0], json.dumps(after) + '\n', text=True)
    value['files'][0]['output_sha256'] = checker.digest(path)
    with pytest.raises(ValueError, match='normalization changed'):
        audit.check_normalization(value, reference)


def test_normalization_cannot_drop_a_process(tmp_path):
    audit = fixture(tmp_path)
    value, reference, _ = normalization(audit)
    value['files'] = []
    with pytest.raises(ValueError, match='incomplete normalization'):
        audit.check_normalization(value, reference)


def test_duplicate_json_keys_fail_closed():
    with pytest.raises(ValueError, match='duplicate JSON key'):
        checker.decode('{"status":"failed","status":"passed"}')


def test_nonfinite_json_measurements_fail_closed():
    with pytest.raises(ValueError, match='nonfinite'):
        checker.decode('{"duration":NaN}')


@pytest.mark.parametrize('target', ['results/p6/phase-gate.json', 'audit/remediation/checks.json'])
def test_checker_cannot_overwrite_historical_evidence(tmp_path, target):
    with pytest.raises(ValueError, match='under results/f01 or build/f01'):
        checker.output_path(tmp_path, tmp_path / target, tmp_path / 'results/f01/acceptance.json', {})


def test_checker_cannot_overwrite_bound_new_evidence(tmp_path):
    audit = fixture(tmp_path)
    name = 'results/f01/study.json'
    write(audit, name, {'status': 'passed'})
    with pytest.raises(ValueError, match='bound evidence'):
        checker.output_path(tmp_path, tmp_path / name, tmp_path / 'results/f01/acceptance.json', audit.manifest)


def test_checker_can_refresh_only_its_own_previous_result(tmp_path):
    path = tmp_path / 'results/f01/checks.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'schema': checker.RESULT_SCHEMA, 'status': 'failed'}))
    assert checker.output_path(tmp_path, path, tmp_path / 'results/f01/acceptance.json', {}) == path
    path.write_text(json.dumps({'schema': 'some-other-artifact'}))
    with pytest.raises(ValueError, match='not a prior'):
        checker.output_path(tmp_path, path, tmp_path / 'results/f01/acceptance.json', {})


def test_missing_acceptance_prerequisites_fail_closed(tmp_path):
    result = checker.Audit({'schema': checker.SCHEMA}, tmp_path).run()
    assert result['status'] == 'failed' and result['failures']


def test_full_check_result_with_bound_evidence_can_be_serialized(tmp_path):
    audit = fixture(tmp_path)
    name = 'results/f01/retained-evidence.json'
    write(audit, name, {'status': 'passed'})
    result = audit.run()
    serialized = json.dumps(result, allow_nan=False)
    reconstructed = json.loads(serialized)
    identity = next(row for row in reconstructed['checks'] if row['check'] == 'evidence:' + name)
    assert identity == {'check': 'evidence:' + name, 'status': 'passed', 'details': name}
    # Missing acceptance sections must still produce a writable failed report.
    assert reconstructed['status'] == 'failed' and reconstructed['failures']


def differential(audit):
    records, budget_record, budget_result = [], None, None
    common = {'status': 'passed', 'seed_base': 1, 'seeds': 1000,
              'operations_per_seed': 10000, 'operations': 10000000}
    for mode, kernel in sorted(checker.PAIRS):
        result = dict(common, mode=mode, kernel=kernel, publications=1, opens=1,
                      nonuniform_payload_publications=1, delivered=1, digest_fnv1a64=1234)
        argv = ['build/release/tiplog_differential', '--seeds', '1000', '--operations',
                '10000', '--mode', mode, '--kernel', kernel]
        name, _ = command(audit, argv, log=json.dumps(result), label=f'{mode}-{kernel}')
        records.append(name)
    budget_result = dict(common, mode_kernel_mask=4095, digest_fnv1a64=5678,
                         **{field: 1 for field in (
                             'publications', 'replay_opens', 'tail_opens', 'polls', 'finite_polls',
                             'zero_polls', 'inspection_yields', 'delivered', 'inspections',
                             'errors', 'pad_inspections')})
    name, budget_record = command(
        audit, ['build/release/tiplog_poll_differential', '--seeds', '1000', '--operations', '10000'],
        log=json.dumps(budget_result), label='budget')
    records.append(name)
    summary = {'status': 'passed', 'preset': 'release', 'seeds_per_campaign': 1000,
               'operations_per_seed': 10000, 'legacy_pairs': sorted(checker.PAIRS), 'records': records}
    name = 'results/f01/differential-release.json'
    write(audit, name, summary)
    return name, summary, budget_record, budget_result


def test_all_legacy_pairs_and_independent_budget_campaign_pass(tmp_path):
    audit = fixture(tmp_path)
    name, _, _, _ = differential(audit)
    assert audit.differential_one('release', name) == {
        'legacy_operations': 90000000, 'budget_operations': 10000000}


@pytest.mark.parametrize('field', ['mode_kernel_mask', 'inspection_yields', 'pad_inspections', 'errors'])
def test_campaign_cannot_omit_mode_cap_pad_or_expiry_coverage(tmp_path, field):
    audit = fixture(tmp_path)
    name, _, record, result = differential(audit)
    result[field] = 0
    path = write(audit, record['log'], json.dumps(result), text=True)
    record['log_sha256'] = checker.digest(path)
    write(audit, 'results/f01/budget.record.json', record)
    with pytest.raises(ValueError, match='omits'):
        audit.differential_one('release', name)


def test_duplicate_campaign_record_cannot_count_as_another_pair(tmp_path):
    audit = fixture(tmp_path)
    name, summary, _, _ = differential(audit)
    summary['records'][0] = summary['records'][1]
    write(audit, name, summary)
    with pytest.raises(ValueError, match='duplicate differential'):
        audit.differential_one('release', name)


def fuzz(audit):
    targets = []
    for target in sorted(checker.FUZZERS):
        binary_name = f'build/fuzz/{target}'
        binary = write(audit, binary_name, 'retained executable placeholder', text=True)
        raw_name = f'build/f01/private/{target}/stderr.log'
        raw = write(audit, raw_name, '#10000 DONE\nstat::number_of_executed_units: 10000\n', text=True)
        targets.append({
            'target': target, 'status': 'passed', 'exit_code': 0,
            'argv': [str(binary), str(audit.root / f'build/f01/private/{target}/corpus'),
                     '-runs=10000', '-max_len=4096',
                     f'-artifact_prefix={audit.root}/build/f01/private/{target}/', '-print_final_stats=1'],
            'binary_sha256': checker.digest(binary), 'completed_executions': 10000,
            'raw_log': raw_name, 'raw_log_sha256': checker.digest(raw),
            'initial_seeds': {'synthetic-0': 'a' * 64},
            'environment': {'TIPLOG_FUZZ_MODE': 'all',
                            'ASAN_OPTIONS': 'detect_leaks=1:abort_on_error=1',
                            'UBSAN_OPTIONS': 'print_stacktrace=1:halt_on_error=1'},
        })
    name = 'results/f01/fuzz-summary.json'
    write(audit, name, {'status': 'passed', 'targets': targets})
    record_name, record = command(audit, ['python3', 'scripts/run_f01_fuzz.py'],
                                  log=json.dumps({'summary': name}), label='fuzz')
    audit.manifest['validations'] = {'fuzz': {'record': record_name, 'summary': name}}
    return name, targets, record


def test_four_source_bound_fuzz_smokes_pass(tmp_path):
    audit = fixture(tmp_path)
    fuzz(audit)
    assert audit.fuzz()['minimum_executions'] == 40000


@pytest.mark.parametrize('change', ['missing_target', 'raw_count', 'leaks_disabled'])
def test_fuzz_summary_cannot_hide_missing_work_or_disabled_leaks(tmp_path, change):
    audit = fixture(tmp_path)
    name, targets, _ = fuzz(audit)
    if change == 'missing_target':
        targets.pop()
    elif change == 'raw_count':
        path = write(audit, targets[0]['raw_log'], '#9 DONE\n', text=True)
        targets[0]['raw_log_sha256'] = checker.digest(path)
    else:
        targets[0]['environment']['ASAN_OPTIONS'] = 'detect_leaks=0:abort_on_error=1'
    write(audit, name, {'status': 'passed', 'targets': targets})
    with pytest.raises(ValueError):
        audit.fuzz()
