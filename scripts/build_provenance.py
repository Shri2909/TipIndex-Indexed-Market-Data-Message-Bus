"""Bind successful project builds and later executions to the same artifacts.

This is local execution provenance, not an attestation against a malicious host.
Snapshots never write into build directories or alter historical evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex

SCHEMA = 'tiplog-build-artifacts-v1'
PRESETS = ('debug', 'release', 'asan-ubsan', 'fuzz')
SHA = re.compile(r'[0-9a-f]{64}\Z')


def identity(path):
    path = Path(path)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': digest, 'bytes': path.stat().st_size}


def cache_values(path):
    """Read data entries only; retain configuration keys without environment dumps."""
    result = {}
    for line in Path(path).read_text().splitlines():
        if not line or line.startswith(('#', '//')) or '=' not in line:
            continue
        key_type, value = line.split('=', 1)
        key, separator, _kind = key_type.partition(':')
        if not separator:
            continue
        if key in result:
            raise ValueError(f'duplicate CMake cache key: {key}')
        result[key] = value
    return result


def capture_build(root, preset, cpp_input_set):
    root = Path(root).resolve()
    if preset not in PRESETS or not isinstance(cpp_input_set, str) or not SHA.fullmatch(cpp_input_set):
        raise ValueError('known preset and exact C++ input-set hash required')
    directory = root/'build'/preset
    if not directory.is_dir() or directory.resolve() != directory:
        raise ValueError('build directory is missing or aliases another location')
    metadata = [directory/'CMakeCache.txt', directory/'compile_commands.json']
    if any(not path.is_file() or path.resolve().parent != directory for path in metadata):
        raise ValueError('build requires local CMake cache and compile commands')
    cache = cache_values(metadata[0])
    if (Path(cache.get('CMAKE_HOME_DIRECTORY', '')).resolve() != root or
            Path(cache.get('CMAKE_CACHEFILE_DIR', '')).resolve() != directory or
            cache.get('CMAKE_EXPORT_COMPILE_COMMANDS', '').upper() not in ('ON', 'TRUE', '1')):
        raise ValueError('CMake cache does not describe this source/build directory')
    commands = json.loads(metadata[1].read_text())
    if not isinstance(commands, list) or not commands or any(
            not isinstance(item, dict) or not isinstance(item.get('file'), str) or
            not isinstance(item.get('directory'), str) or
            not (isinstance(item.get('command'), str) or isinstance(item.get('arguments'), list))
            for item in commands):
        raise ValueError('compile commands must describe a nonempty compilation database')
    executables = [path for path in sorted(directory.iterdir()) if path.is_file() and os.access(path, os.X_OK)]
    if not executables:
        raise ValueError('no built project executables')
    if any(path.resolve().parent != directory for path in executables):
        raise ValueError('project executable aliases a file outside its build directory')
    configuration = {key: value for key, value in sorted(cache.items())
                     if key.startswith(('CMAKE_CXX_FLAGS', 'CMAKE_EXE_LINKER_FLAGS',
                                        'CMAKE_SHARED_LINKER_FLAGS', 'TIPLOG_'))
                     or key in {'CMAKE_BUILD_TYPE', 'CMAKE_CXX_STANDARD', 'CMAKE_CXX_EXTENSIONS',
                                'CMAKE_GENERATOR', 'CMAKE_MAKE_PROGRAM', 'BUILD_TESTING',
                                'CMAKE_EXPORT_COMPILE_COMMANDS', 'BENCHMARK_ENABLE_EXCEPTIONS'}}
    detection = sorted((directory/'CMakeFiles').glob('*/CMakeCXXCompiler.cmake'))
    if len(detection) != 1:
        raise ValueError('missing or ambiguous CMake compiler detection')
    text = detection[0].read_text()
    detected_compiler = re.search(r'^set\(CMAKE_CXX_COMPILER "([^"\n]+)"\)', text, re.M)
    if detected_compiler is None:
        raise ValueError('missing detected C++ compiler')
    compiler = Path(detected_compiler.group(1))
    configured = cache.get('CMAKE_CXX_COMPILER', '')
    configured_path = Path(configured) if Path(configured).is_absolute() else Path(shutil.which(configured) or '')
    if (not compiler.is_absolute() or not compiler.is_file() or not configured_path.is_file()
            or configured_path.resolve() != compiler.resolve()):
        raise ValueError('configured and detected C++ compiler identities disagree')
    compiler_info = {'path': str(compiler.resolve()), **identity(compiler)}
    for key in ('ID', 'VERSION'):
        match = re.search(r'^set\(CMAKE_CXX_COMPILER_' + key + r' "([^"\n]+)"\)', text, re.M)
        if match is None:
            raise ValueError(f'missing CMake compiler {key.lower()}')
        compiler_info[key.lower()] = match.group(1)
    dependencies = []
    if 'benchmark_SOURCE_DIR' in cache:
        benchmark = Path(cache['benchmark_SOURCE_DIR'])/'src/benchmark.cc'
        if not benchmark.is_file() or not benchmark.resolve().is_relative_to(directory):
            raise ValueError('missing or external Google Benchmark patched source')
        dependencies.append(benchmark)
    return {'schema': SCHEMA, 'preset': preset, 'cpp_input_set': cpp_input_set,
            'build_directory': directory.relative_to(root).as_posix(),
            'configuration': configuration, 'compiler': compiler_info,
            'artifacts': {path.relative_to(root).as_posix(): identity(path)
                          for path in [*metadata, detection[0], *dependencies, *executables]}}


def verify_build(snapshot, root, preset, cpp_input_set):
    """Raise on missing, stale, added, removed or changed build artifacts."""
    if not isinstance(snapshot, dict) or snapshot != capture_build(root, preset, cpp_input_set):
        raise ValueError('build artifacts/configuration do not match the recorded snapshot')
    return True


def preset_variables(root, preset):
    """Resolve the repository's declared configure-preset inheritance."""
    document = json.loads((Path(root)/'CMakePresets.json').read_text())
    entries = {item['name']: item for item in document['configurePresets']}
    if len(entries) != len(document['configurePresets']):
        raise ValueError('duplicate configure preset')
    def resolve(name, active):
        if name not in entries or name in active:
            raise ValueError('missing or cyclic configure-preset inheritance')
        entry = entries[name]
        parents = entry.get('inherits', [])
        parents = [parents] if isinstance(parents, str) else parents
        values = {}
        # CMake gives an earlier parent precedence over a later parent.
        for parent in reversed(parents):
            values.update(resolve(parent, active | {name}))
        values.update(entry.get('cacheVariables', {}))
        return values
    values = resolve(preset, set())
    return {name: str(value.get('value') if isinstance(value, dict) else value)
            for name, value in values.items()}


def _required_flags(actual, required, *, sanitizer):
    """Check token presence and options whose later occurrence overrides it."""
    normalized = []
    index = 0
    while index < len(actual):
        token = actual[index]
        if token in ('-D', '-U') and index+1 < len(actual):
            index += 1
            token += actual[index]
        normalized.append(token)
        index += 1
    actual = normalized
    # These options can hide flags or code in files/passes which the recorded
    # source/compilation inventory does not bind. Supported presets do not use
    # them. Reject rather than pretend to emulate the compiler driver.
    indirect = ('-Xclang', '-mllvm', '-Xpreprocessor', '-Xassembler', '-Xlinker',
                '-Wp,', '-Wa,', '-Wl,', '--config', '-specs', '--specs', '-wrapper',
                '-fplugin', '-fpass-plugin', '-load', '-include', '--include', '-imacros',
                '-ivfsoverlay', '-vfsoverlay', '-fmodule-file', '-fmodule-map-file',
                '-fprebuilt-module-path', '-fmodules', '--gcc-toolchain', '-gcc-toolchain',
                '--sysroot', '-isysroot', '-resource-dir', '-B', '-ccc-', '-cc1',
                '-fprofile-use', '-fprofile-instr-use', '-fauto-profile')
    if any(token.startswith(('@', *indirect)) for token in actual):
        raise ValueError('indirect compiler flags or undeclared compilation inputs are unsupported')
    if any(token.startswith(('-fsanitize', '-fno-sanitize')) and token not in required
           for token in actual):
        raise ValueError('undeclared sanitizer suppression or configuration flag')
    declared_ndebug = any(token.startswith('-D') and token[2:].split('=', 1)[0] == 'NDEBUG'
                          for token in required)
    if not declared_ndebug and any(token.startswith('-D') and token[2:].split('=', 1)[0] == 'NDEBUG'
                                   for token in actual):
        raise ValueError('NDEBUG disables assertions required by the declared preset')
    if not set(required) <= set(actual):
        raise ValueError('compilation/link flags omit required preset tokens')
    if sanitizer and any(token.startswith(('-fno-sanitize=', '-fsanitize-recover='))
                         or token in ('-fsanitize-recover', '-fno-sanitize-recover') for token in actual):
        raise ValueError('sanitizer instrumentation or error recovery was overridden')
    for pattern in (r'-O(?:[0-3sgz]|fast)', r'-g(?:[0-3])?', r'-f(?:no-)?omit-frame-pointer',
                    r'-std=.+'):
        wanted = [token for token in required if re.fullmatch(pattern, token)]
        observed = [token for token in actual if re.fullmatch(pattern, token)]
        if wanted and (not observed or observed[-1] != wanted[-1]):
            raise ValueError('effective compilation flag overrides its preset')
    for token in required:
        if not token.startswith('-D'):
            continue
        macro = token[2:].split('=', 1)[0]
        definitions = [flag for flag in actual if flag.startswith(('-D', '-U'))
                       and flag[2:].split('=', 1)[0] == macro]
        if not definitions or definitions[-1] != token:
            raise ValueError('required preset macro was overridden')


def validate_configuration(snapshot, root, preset):
    """Require actual preset configuration, including compiler instrumentation.

    Recording a directory named ``asan-ubsan`` and setting ASAN_OPTIONS alone
    cannot establish that the compiled project code contains sanitizer checks.
    """
    root = Path(root).resolve()
    if preset not in PRESETS or snapshot.get('schema') != SCHEMA or snapshot.get('preset') != preset:
        raise ValueError('unknown or mismatched build configuration preset')
    declared = preset_variables(root, preset)
    configuration = snapshot['configuration']
    expected_compiler = 'GNU' if preset in ('debug', 'release') else 'Clang'
    if snapshot['compiler'].get('id') != expected_compiler:
        raise ValueError('compiler does not match the supported preset')
    for name in ('CMAKE_BUILD_TYPE', 'CMAKE_CXX_STANDARD', 'CMAKE_CXX_EXTENSIONS'):
        if configuration.get(name) != declared.get(name):
            raise ValueError('build configuration differs from declared preset: '+name)
    truth = lambda value: str(value).upper() in ('ON', 'TRUE', 'YES', '1')
    if not truth(configuration.get('BUILD_TESTING', 'OFF')):
        raise ValueError('preset test compilation is disabled')
    if truth(configuration.get('TIPLOG_ENABLE_FUZZING', 'OFF')) != (preset == 'fuzz'):
        raise ValueError('fuzz instrumentation does not match its preset')
    sanitizer = preset in ('asan-ubsan', 'fuzz')
    build_type = declared['CMAKE_BUILD_TYPE'].upper()
    def flags(values, prefix):
        return shlex.split(values.get(prefix, '')) + shlex.split(values.get(prefix+'_'+build_type, ''))
    required_cxx = flags(declared, 'CMAKE_CXX_FLAGS')
    _required_flags(flags(configuration, 'CMAKE_CXX_FLAGS'), required_cxx, sanitizer=sanitizer)
    for prefix in ('CMAKE_EXE_LINKER_FLAGS', 'CMAKE_SHARED_LINKER_FLAGS'):
        _required_flags(flags(configuration, prefix), flags(declared, prefix), sanitizer=sanitizer)
    if any(name.endswith('/benchmark-src/src/benchmark.cc') for name in snapshot['artifacts']):
        if not truth(configuration.get('BENCHMARK_ENABLE_EXCEPTIONS', 'OFF')):
            raise ValueError('patched Benchmark output handling requires C++ exceptions')
    required_compile = [*required_cxx, '-std=c++'+declared['CMAKE_CXX_STANDARD']]
    database = json.loads((root/'build'/preset/'compile_commands.json').read_text())
    owned = 0
    for entry in database:
        directory = Path(entry['directory'])
        source = Path(entry['file'])
        source = (source if source.is_absolute() else directory/source).resolve()
        if not source.is_relative_to(root) or source.relative_to(root).parts[0] not in ('src', 'tools', 'bench', 'tests'):
            continue
        owned += 1
        argv = entry.get('arguments')
        argv = shlex.split(entry['command']) if argv is None else argv
        if not isinstance(argv, list) or not argv or not all(isinstance(token, str) for token in argv):
            raise ValueError('invalid project compilation command')
        compiler = Path(argv[0])
        compiler = compiler if compiler.is_absolute() else Path(shutil.which(argv[0]) or '')
        if not compiler.is_file() or compiler.resolve() != Path(snapshot['compiler']['path']).resolve():
            raise ValueError('project command uses another compiler or launcher')
        _required_flags(argv[1:], required_compile, sanitizer=sanitizer)
    if not owned:
        raise ValueError('compilation database omits project-owned source entries')
    return True


def command_build(command, root, cwd=None):
    """Recognize full preset builds, preset CTest and direct/wrapped binaries."""
    if not command:
        return None
    root, cwd = Path(root).resolve(), Path(cwd or root).resolve()
    scripts = {(candidate if candidate.is_absolute() else cwd/candidate).resolve()
               for candidate in map(Path, command) if candidate.name in
               ('run_f01_fuzz.py', 'run_f01_differentials.py')}
    if root/'scripts/run_f01_fuzz.py' in scripts:
        return {'preset': 'fuzz', 'kind': 'launcher', 'full_build': False}
    if root/'scripts/run_f01_differentials.py' in scripts:
        if '--preset' not in command or command.index('--preset')+1 >= len(command):
            raise ValueError('differential launcher requires an explicit preset')
        preset = command[command.index('--preset')+1]
        if preset not in PRESETS:
            raise ValueError('unknown differential launcher preset')
        return {'preset': preset, 'kind': 'launcher', 'full_build': False}
    name = Path(command[0]).name
    if name in ('cmake', 'ctest') and '--preset' in command:
        at = command.index('--preset')
        if at+1 >= len(command) or command[at+1] not in PRESETS:
            raise ValueError('missing or unknown build/test preset')
        preset = command[at+1]
        if name == 'ctest':
            return {'preset': preset, 'kind': 'ctest', 'full_build': False}
        if '--build' in command:
            return {'preset': preset, 'kind': 'build',
                    'full_build': not any(arg in ('--target', '-t', '--') or
                                          arg.startswith('--target=') for arg in command)}
        return None  # Configure does not produce compiled artifacts.
    found = set()
    for token in command:
        candidate = Path(token)
        candidate = (candidate if candidate.is_absolute() else cwd/candidate).resolve()
        for preset in PRESETS:
            if candidate.parent == root/'build'/preset and candidate.is_file() and os.access(candidate, os.X_OK):
                found.add(preset)
    if len(found) > 1:
        raise ValueError('command refers to binaries from multiple presets')
    return {'preset': found.pop(), 'kind': 'binary', 'full_build': False} if found else None
