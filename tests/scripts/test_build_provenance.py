"""Current-source acceptance must bind tests to a successful compiled build."""
import importlib.util
import json
from pathlib import Path
import shlex
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('build_provenance_test_helper', ROOT/'scripts/build_provenance.py')
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)
CPP = 'a'*64


def build_tree(root, preset='release'):
    directory = root/'build'/preset
    directory.mkdir(parents=True)
    compiler = root/'compiler'; compiler.write_bytes(b'compiler identity')
    cache = '\n'.join([f'CMAKE_HOME_DIRECTORY:INTERNAL={root}',
                       f'CMAKE_CACHEFILE_DIR:INTERNAL={directory}',
                       'CMAKE_EXPORT_COMPILE_COMMANDS:BOOL=ON',
                       f'CMAKE_CXX_COMPILER:FILEPATH={compiler}',
                       'CMAKE_BUILD_TYPE:STRING=Release',
                       'CMAKE_CXX_FLAGS_RELEASE:STRING=-O2 -DNDEBUG',
                       'TIPLOG_ENABLE_FUZZING:BOOL=OFF',
                       'UNRELATED_SECRET:STRING=must not appear in configuration'])+'\n'
    (directory/'CMakeCache.txt').write_text(cache)
    (directory/'compile_commands.json').write_text(json.dumps([
        dict(directory=str(directory), file=str(root/'src/example.cpp'), command='c++ -c example.cpp')]))
    detection = directory/'CMakeFiles/4.4.0/CMakeCXXCompiler.cmake'
    detection.parent.mkdir(parents=True)
    detection.write_text(f'set(CMAKE_CXX_COMPILER "{compiler}")\n'
                         'set(CMAKE_CXX_COMPILER_ID "GNU")\nset(CMAKE_CXX_COMPILER_VERSION "15.2.0")\n')
    binary = directory/'tiplog_example'; binary.write_bytes(b'project executable'); binary.chmod(0o755)
    vendored = directory/'_deps/bin/upstream'; vendored.parent.mkdir(parents=True)
    vendored.write_bytes(b'upstream'); vendored.chmod(0o755)
    return directory, binary


def test_snapshot_exact_identity_and_sanitized_configuration(tmp_path):
    directory, binary = build_tree(tmp_path)
    snapshot = provenance.capture_build(tmp_path, 'release', CPP)
    assert snapshot['schema'] == provenance.SCHEMA
    assert snapshot['compiler']['id'] == 'GNU' and snapshot['compiler']['version'] == '15.2.0'
    assert snapshot['configuration']['CMAKE_CXX_FLAGS_RELEASE'] == '-O2 -DNDEBUG'
    assert 'UNRELATED_SECRET' not in snapshot['configuration']
    assert set(snapshot['artifacts']) == {
        'build/release/CMakeCache.txt', 'build/release/compile_commands.json',
        'build/release/CMakeFiles/4.4.0/CMakeCXXCompiler.cmake', 'build/release/tiplog_example'}
    assert provenance.verify_build(snapshot, tmp_path, 'release', CPP)
    binary.write_bytes(b'stale replacement')
    with pytest.raises(ValueError, match='match'): provenance.verify_build(snapshot, tmp_path, 'release', CPP)


@pytest.mark.parametrize('damage', ['missing_cache', 'missing_commands', 'empty_commands', 'missing_binary',
                                   'new_binary', 'flags', 'compiler', 'source', 'duplicate_cache', 'alias'])
def test_missing_stale_filtered_or_changed_artifacts_fail_closed(tmp_path, damage):
    directory, binary = build_tree(tmp_path)
    snapshot = provenance.capture_build(tmp_path, 'release', CPP)
    if damage == 'missing_cache': (directory/'CMakeCache.txt').unlink()
    elif damage == 'missing_commands': (directory/'compile_commands.json').unlink()
    elif damage == 'empty_commands': (directory/'compile_commands.json').write_text('[]')
    elif damage == 'missing_binary': binary.unlink()
    elif damage == 'new_binary':
        extra = directory/'unexpected'; extra.write_text('executable'); extra.chmod(0o755)
    elif damage == 'flags':
        cache = directory/'CMakeCache.txt'; cache.write_text(cache.read_text().replace('-O2', '-O0'))
    elif damage == 'compiler': (tmp_path/'compiler').write_bytes(b'other compiler')
    elif damage == 'source': CPP_other = 'b'*64
    elif damage == 'duplicate_cache':
        with (directory/'CMakeCache.txt').open('a') as stream: stream.write('CMAKE_BUILD_TYPE:STRING=Debug\n')
    else:
        outside = tmp_path/'external'; outside.write_bytes(b'external'); outside.chmod(0o755)
        binary.unlink(); binary.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        provenance.verify_build(snapshot, tmp_path, 'release', CPP_other if damage == 'source' else CPP)


def test_command_classification_distinguishes_full_build_from_partial(tmp_path):
    _, binary = build_tree(tmp_path)
    assert provenance.command_build(['cmake', '--build', '--preset', 'release', '--parallel', '2'], tmp_path) == {
        'preset': 'release', 'kind': 'build', 'full_build': True}
    assert provenance.command_build(['cmake', '--build', '--preset', 'release', '--target', 'tiplog_example'], tmp_path)['full_build'] is False
    assert provenance.command_build(['ctest', '--preset', 'release'], tmp_path)['kind'] == 'ctest'
    assert provenance.command_build(['taskset', '-c', '2', str(binary), '--seeds', '10'], tmp_path)['kind'] == 'binary'
    assert provenance.command_build(['cmake', '--preset', 'release'], tmp_path) is None
    assert provenance.command_build(['python', '-m', 'pytest'], tmp_path) is None
    assert provenance.command_build(['python', 'scripts/run_f01_fuzz.py'], tmp_path)['preset'] == 'fuzz'
    assert provenance.command_build(['python', 'scripts/run_f01_differentials.py', '--preset', 'release'], tmp_path)['preset'] == 'release'


def test_named_compiler_cache_resolves_against_detected_compiler(tmp_path, monkeypatch):
    directory, _ = build_tree(tmp_path)
    compiler = tmp_path/'compiler'
    cache = directory/'CMakeCache.txt'
    cache.write_text(cache.read_text().replace(f'CMAKE_CXX_COMPILER:FILEPATH={compiler}',
                                              'CMAKE_CXX_COMPILER:UNINITIALIZED=g++'))
    monkeypatch.setattr(provenance.shutil, 'which', lambda name: str(compiler) if name == 'g++' else None)
    assert provenance.capture_build(tmp_path, 'release', CPP)['compiler']['path'] == str(compiler)


def test_configured_benchmark_patch_and_exception_flag_are_bound(tmp_path):
    directory, _ = build_tree(tmp_path)
    source = directory/'_deps/benchmark-src/src/benchmark.cc'
    source.parent.mkdir(parents=True); source.write_text('patched source')
    with (directory/'CMakeCache.txt').open('a') as stream:
        stream.write(f'benchmark_SOURCE_DIR:STATIC={source.parent.parent}\nBENCHMARK_ENABLE_EXCEPTIONS:BOOL=ON\n')
    snapshot = provenance.capture_build(tmp_path, 'release', CPP)
    assert snapshot['configuration']['BENCHMARK_ENABLE_EXCEPTIONS'] == 'ON'
    assert source.relative_to(tmp_path).as_posix() in snapshot['artifacts']
    source.write_text('changed patch')
    with pytest.raises(ValueError): provenance.verify_build(snapshot, tmp_path, 'release', CPP)


def configured_tree(root, preset):
    directory, _ = build_tree(root, preset)
    (root/'CMakePresets.json').write_bytes((ROOT/'CMakePresets.json').read_bytes())
    values = provenance.cache_values(directory/'CMakeCache.txt')
    values.update(provenance.preset_variables(root, preset))
    values['CMAKE_CXX_COMPILER'] = str(root/'compiler')
    values['TIPLOG_ENABLE_FUZZING'] = 'ON' if preset == 'fuzz' else 'OFF'
    (directory/'CMakeCache.txt').write_text(''.join(f'{key}:STRING={value}\n' for key, value in values.items()))
    detection = directory/'CMakeFiles/4.4.0/CMakeCXXCompiler.cmake'
    if preset in ('asan-ubsan', 'fuzz'):
        detection.write_text(detection.read_text().replace('"GNU"', '"Clang"'))
    source = root/'src/example.cpp'; source.parent.mkdir(); source.write_text('int example;\n')
    required = shlex.split(values.get('CMAKE_CXX_FLAGS', ''))
    required += shlex.split(values.get('CMAKE_CXX_FLAGS_'+values['CMAKE_BUILD_TYPE'].upper(), ''))
    command = [str(root/'compiler'), *required, '-std=c++20', '-c', str(source)]
    (directory/'compile_commands.json').write_text(json.dumps([
        dict(directory=str(directory), file=str(source), command=shlex.join(command))]))
    return directory, command


@pytest.mark.parametrize('preset', provenance.PRESETS)
def test_actual_declared_preset_configuration_is_required_and_supported(tmp_path, preset):
    configured_tree(tmp_path, preset)
    snapshot = provenance.capture_build(tmp_path, preset, CPP)
    assert provenance.validate_configuration(snapshot, tmp_path, preset)


@pytest.mark.parametrize('damage', ['wrong_build_type', 'wrong_compiler', 'testing_off', 'fuzz_off',
                                   'missing_compile_san', 'missing_cache_san', 'recover', 'disable_san',
                                   'opt_override', 'missing_frame', 'wrong_standard', 'link_disabled',
                                   'shared_link_missing', 'no_project_entries', 'other_compiler',
                                   'cache_recover'])
def test_wrong_or_overridden_sanitizer_configuration_cannot_pass(tmp_path, damage):
    preset = 'fuzz' if damage == 'fuzz_off' else 'asan-ubsan'
    directory, command = configured_tree(tmp_path, preset)
    cache = provenance.cache_values(directory/'CMakeCache.txt')
    if damage == 'wrong_build_type': cache['CMAKE_BUILD_TYPE'] = 'Release'
    elif damage == 'testing_off': cache['BUILD_TESTING'] = 'OFF'
    elif damage == 'fuzz_off': cache['TIPLOG_ENABLE_FUZZING'] = 'OFF'
    elif damage == 'missing_compile_san': command.remove('-fsanitize=address,undefined')
    elif damage == 'missing_cache_san':
        cache['CMAKE_CXX_FLAGS_DEBUG'] = cache['CMAKE_CXX_FLAGS_DEBUG'].replace('-fsanitize=address,undefined', '')
    elif damage == 'recover': command.append('-fsanitize-recover=all')
    elif damage == 'disable_san': command.append('-fno-sanitize=undefined')
    elif damage == 'opt_override': command.append('-O0')
    elif damage == 'missing_frame': command.remove('-fno-omit-frame-pointer')
    elif damage == 'wrong_standard': command.append('-std=c++17')
    elif damage == 'link_disabled': cache['CMAKE_EXE_LINKER_FLAGS'] += ' -fno-sanitize=all'
    elif damage == 'shared_link_missing': cache['CMAKE_SHARED_LINKER_FLAGS'] = ''
    elif damage == 'other_compiler': command[0] = '/bin/echo'
    elif damage == 'cache_recover': cache['CMAKE_CXX_FLAGS_DEBUG'] += ' -fsanitize-recover=all'
    elif damage == 'wrong_compiler':
        detection = directory/'CMakeFiles/4.4.0/CMakeCXXCompiler.cmake'
        detection.write_text(detection.read_text().replace('"Clang"', '"GNU"'))
    (directory/'CMakeCache.txt').write_text(''.join(f'{key}:STRING={value}\n' for key, value in cache.items()))
    database = [dict(directory=str(directory), file=str(tmp_path/'src/example.cpp'), arguments=command)]
    if damage == 'no_project_entries': database[0]['file'] = str(directory/'_deps/example.cpp')
    (directory/'compile_commands.json').write_text(json.dumps(database))
    snapshot = provenance.capture_build(tmp_path, preset, CPP)
    with pytest.raises(ValueError): provenance.validate_configuration(snapshot, tmp_path, preset)


@pytest.mark.parametrize('damage', ['fuzz_in_release', 'undefine_assertion', 'undefine_assertion_separate', 'optimization'])
def test_release_effective_flags_and_macro_overrides_are_rejected(tmp_path, damage):
    directory, command = configured_tree(tmp_path, 'release')
    if damage == 'fuzz_in_release':
        cache = directory/'CMakeCache.txt'; cache.write_text(cache.read_text().replace('TIPLOG_ENABLE_FUZZING:STRING=OFF', 'TIPLOG_ENABLE_FUZZING:STRING=ON'))
    elif damage == 'undefine_assertion': command.append('-UNDEBUG')
    elif damage == 'undefine_assertion_separate': command += ['-U', 'NDEBUG']
    else: command.append('-O0')
    (directory/'compile_commands.json').write_text(json.dumps([
        dict(directory=str(directory), file=str(tmp_path/'src/example.cpp'), arguments=command)]))
    snapshot = provenance.capture_build(tmp_path, 'release', CPP)
    with pytest.raises(ValueError): provenance.validate_configuration(snapshot, tmp_path, 'release')


@pytest.mark.parametrize('surface', ['compile', 'cache', 'link'])
def test_response_file_cannot_hide_the_peer_reproduced_sanitizer_disable(tmp_path, surface):
    directory, command = configured_tree(tmp_path, 'asan-ubsan')
    response = tmp_path/'disable.rsp'
    response.write_text('-fno-sanitize=all\n')
    token = '@'+str(response)
    if surface == 'compile':
        command.append(token)
        (directory/'compile_commands.json').write_text(json.dumps([
            dict(directory=str(directory), file=str(tmp_path/'src/example.cpp'), arguments=command)]))
    else:
        key = 'CMAKE_CXX_FLAGS_DEBUG' if surface == 'cache' else 'CMAKE_EXE_LINKER_FLAGS'
        cache = provenance.cache_values(directory/'CMakeCache.txt')
        cache[key] += ' '+token
        (directory/'CMakeCache.txt').write_text(''.join(f'{key}:STRING={value}\n' for key, value in cache.items()))
    snapshot = provenance.capture_build(tmp_path, 'asan-ubsan', CPP)
    with pytest.raises(ValueError, match='indirect'):
        provenance.validate_configuration(snapshot, tmp_path, 'asan-ubsan')


@pytest.mark.parametrize('extra', [
    ['-fsanitize-ignorelist=external.txt'], ['-fsanitize-blacklist=external.txt'],
    ['-Xclang', '-disable-llvm-passes'], ['-mllvm', '-asan-instrument-reads=false'],
    ['-Xpreprocessor', '-DNDEBUG'], ['-Wp,-DNDEBUG'],
    ['-Xassembler', '@assembler.rsp'], ['-Wa,@assembler.rsp'],
    ['-Xlinker', '@linker.rsp'], ['-Wl,@linker.rsp'],
    ['--config=external.cfg'], ['--config', 'external.cfg'], ['--config-user-dir=external'],
    ['-specs=external.specs'], ['-wrapper', 'external-wrapper'], ['-Bexternal-toolchain'],
    ['-fplugin=external.so'], ['-fpass-plugin=external.so'],
    ['-include', 'external.h'], ['-includeexternal.h'], ['-include-pch', 'external.pch'],
    ['-imacros', 'external.h'], ['-ivfsoverlay', 'external.yaml'],
    ['-fmodule-file=external.pcm'], ['-fmodule-map-file=external.modulemap'],
    ['-fprebuilt-module-path=external'], ['-fmodules-cache-path=external'],
    ['--gcc-toolchain=external'], ['--sysroot=external'], ['-isysroot', 'external'],
    ['-resource-dir', 'external'], ['-fprofile-instr-use=external.profdata'],
    ['-fno-sanitize-address-use-after-scope'],
])
def test_undeclared_suppression_or_compiler_input_cannot_bypass_inspected_flags(tmp_path, extra):
    directory, command = configured_tree(tmp_path, 'asan-ubsan')
    command += extra
    (directory/'compile_commands.json').write_text(json.dumps([
        dict(directory=str(directory), file=str(tmp_path/'src/example.cpp'), arguments=command)]))
    snapshot = provenance.capture_build(tmp_path, 'asan-ubsan', CPP)
    with pytest.raises(ValueError, match='indirect|undeclared sanitizer'):
        provenance.validate_configuration(snapshot, tmp_path, 'asan-ubsan')


@pytest.mark.parametrize('preset', ['debug', 'asan-ubsan', 'fuzz'])
@pytest.mark.parametrize('extra', [['-DNDEBUG'], ['-D', 'NDEBUG'], ['-DNDEBUG=0']])
def test_undeclared_ndebug_cannot_silently_disable_assertions(tmp_path, preset, extra):
    directory, command = configured_tree(tmp_path, preset)
    command += extra
    (directory/'compile_commands.json').write_text(json.dumps([
        dict(directory=str(directory), file=str(tmp_path/'src/example.cpp'), arguments=command)]))
    snapshot = provenance.capture_build(tmp_path, preset, CPP)
    with pytest.raises(ValueError, match='NDEBUG'):
        provenance.validate_configuration(snapshot, tmp_path, preset)


def test_ordinary_warning_flags_remain_extensible(tmp_path):
    directory, command = configured_tree(tmp_path, 'asan-ubsan')
    command += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter']
    (directory/'compile_commands.json').write_text(json.dumps([
        dict(directory=str(directory), file=str(tmp_path/'src/example.cpp'), arguments=command)]))
    snapshot = provenance.capture_build(tmp_path, 'asan-ubsan', CPP)
    assert provenance.validate_configuration(snapshot, tmp_path, 'asan-ubsan')


def recorder(monkeypatch, root):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    spec = importlib.util.spec_from_file_location('run_f01_check_provenance_test', ROOT/'scripts/run_f01_check.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(module, 'input_sets', lambda: dict(cpp=CPP, python='b'*64))
    return module


@pytest.mark.parametrize('kind', ['build', 'ctest', 'binary'])
def test_recorder_binds_successful_build_and_later_executions(tmp_path, monkeypatch, kind):
    _, binary = build_tree(tmp_path)
    module = recorder(monkeypatch, tmp_path)
    command = {'build': ['cmake', '--build', '--preset', 'release', '--parallel', '2'],
               'ctest': ['ctest', '--preset', 'release'], 'binary': [str(binary), '--seeds', '1']}[kind]
    monkeypatch.setattr('sys.argv', ['run_f01_check', '--cwd', str(tmp_path), 'check', '--', *command])
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    assert module.main() == 0
    record = json.loads(next((tmp_path/'results/f01/checks').glob('*.json')).read_text())
    assert record['status'] == 'passed' and record['command_exit_code'] == 0
    assert record['build_execution']['kind'] == kind
    if kind == 'build': assert record['build_provenance'] == record['build_artifacts_after']
    else: assert record['build_artifacts_before'] == record['build_artifacts_after']


def test_recorder_does_not_run_unbound_test_command(tmp_path, monkeypatch):
    module = recorder(monkeypatch, tmp_path)
    monkeypatch.setattr('sys.argv', ['run_f01_check', '--cwd', str(tmp_path), 'check', '--', 'ctest', '--preset', 'release'])
    def forbidden(*args, **kwargs): pytest.fail('test ran without build provenance')
    monkeypatch.setattr(module.subprocess, 'run', forbidden)
    assert module.main() == 125
    record = json.loads(next((tmp_path/'results/f01/checks').glob('*.json')).read_text())
    assert record['status'] == 'failed' and 'provenance_error' in record
    assert 'command_exit_code' not in record


def test_recorder_rejects_binary_replacement_during_test(tmp_path, monkeypatch):
    _, binary = build_tree(tmp_path)
    module = recorder(monkeypatch, tmp_path)
    monkeypatch.setattr('sys.argv', ['run_f01_check', '--cwd', str(tmp_path), 'check', '--', 'ctest', '--preset', 'release'])
    def changed(*args, **kwargs):
        binary.write_bytes(b'changed during execution')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', changed)
    assert module.main() == 125
    record = json.loads(next((tmp_path/'results/f01/checks').glob('*.json')).read_text())
    assert record['command_exit_code'] == 0 and record['status'] == 'failed'
    assert record['build_artifacts_before'] != record['build_artifacts_after']


@pytest.mark.parametrize('active', [False, True])
def test_recorder_explicitly_binds_full_suite_selection_environment(tmp_path, monkeypatch, active):
    module = recorder(monkeypatch, tmp_path)
    values = {'GTEST_FILTER': '-PollBudget.TailExpiryAfterFailedAppendReportsActuallyDeliveredPrefix',
              'GTEST_TOTAL_SHARDS': '999999', 'GTEST_SHARD_INDEX': '999998', 'GTEST_REPEAT': '0',
              'TESTBRIDGE_TEST_ONLY': 'NoMatchingCase', 'CTEST_TESTS_TO_RUN': '0,0,1',
              'PYTEST_ADDOPTS': '-k not_the_new_regression', 'PYTEST_PLUGINS': 'injected_plugin'}
    for name, value in values.items():
        if active: monkeypatch.setenv(name, value)
        else: monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
    monkeypatch.setattr('sys.argv', ['run_f01_check', '--cwd', str(tmp_path), 'check', '--',
                                   '.venv/bin/python', '-m', 'pytest'])
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    assert module.main() == 0
    record = json.loads(next((tmp_path/'results/f01/checks').glob('*.json')).read_text())
    assert all(name in record['environment'] for name in values)
    assert {name: record['environment'][name] for name in values} == {
        name: value if active else None for name, value in values.items()}
    assert record['environment']['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'
