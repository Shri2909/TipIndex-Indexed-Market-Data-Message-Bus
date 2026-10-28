#!/usr/bin/env python3
"""Assemble an F-01 acceptance candidate from completed, recorded evidence.

This records identities and follows the declared evidence references; it does
not execute tests or declare acceptance. Run check_f01.py on the resulting
candidate separately. Historical results and previous candidates are preserved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from check_remediation import digest, input_sets, local, source_inventory

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'tiplog-f01-acceptance-v1'
PRESETS = ('debug', 'release', 'asan-ubsan', 'fuzz')
BENCHMARK_FIELDS = (
    'records', 'original_raw', 'raw', 'normalization', 'normalizer_record',
    'summary', 'contracts', 'contract_record', 'preflight_records', 'preflight_raw',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError(f'nonfinite JSON value in {path}: {value}')))


class Candidate:
    def __init__(self, root=ROOT):
        self.root = root.resolve()
        self.evidence = {}
        self.records = set()

    def name(self, value):
        require(isinstance(value, str) and value, 'missing evidence path')
        return local(self.root, value).relative_to(self.root).as_posix()

    def bind(self, value, expected_sha=None):
        name = self.name(value)
        path = local(self.root, name)
        require(path.is_file(), f'missing required evidence: {name}')
        identity = {'sha256': digest(path), 'bytes': path.stat().st_size}
        if expected_sha is not None:
            require(identity['sha256'] == expected_sha, f'nested identity differs: {name}')
        if name in self.evidence:
            require(self.evidence[name] == identity, f'evidence changed during assembly: {name}')
        self.evidence[name] = identity
        return name

    def read(self, value):
        return read_json(local(self.root, self.bind(value)))

    def binding(self, binding):
        for field in ('source_freeze', 'plan', 'protocol', 'runner', 'binary'):
            self.bind(binding[field], binding[field + '_sha256'])
        self.bind(binding['build_record'], binding['build_record_sha256'])
        self.record(binding['build_record'])

    def record(self, value):
        name = self.bind(value)
        if name in self.records:
            return read_json(local(self.root, name))
        self.records.add(name)
        record = self.read(name)
        self.bind(record['log'], record['log_sha256'])
        for field in ('build_provenance', 'build_artifacts_before', 'build_artifacts_after'):
            for artifact, identity in record.get(field, {}).get('artifacts', {}).items():
                self.bind(artifact, identity['sha256'])
        if 'binding' in record:
            self.binding(record['binding'])
        if 'raw_output' in record:
            self.bind(record['raw_output'], record['raw_sha256'])
        argv = record['argv']
        require(isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv),
                f'missing command vector: {name}')
        # Bind project-built executables, never system Python/CMake symlinks or
        # entire corpus directories. Specific file arguments below are inputs
        # that the independent checker also follows through the command line.
        executable = Path(argv[0])
        if (executable.is_absolute() and executable.is_relative_to(self.root / 'build')) or argv[0].startswith('build/'):
            self.bind(argv[0], record.get('binary_sha256'))
        for option in ('--mapping', '--matrix', '--binary'):
            if option in argv:
                index = argv.index(option)
                require(index + 1 < len(argv), f'missing {option} value in {name}')
                self.bind(argv[index + 1])
        return record

    def latest_record(self, pattern, *, passed_only=False):
        paths = sorted((self.root / 'results/f01/checks').glob(pattern))
        if passed_only:
            paths = [path for path in paths if read_json(path).get('status') == 'passed'
                     and read_json(path).get('exit_code') == 0]
        require(paths, f'missing required completed command matching {pattern}')
        name = paths[-1].relative_to(self.root).as_posix()
        record = self.record(name)
        require(record.get('status') == 'passed' and type(record.get('exit_code')) is int
                and record['exit_code'] == 0, f'latest required command did not pass: {name}')
        return name, record

    def benchmarks(self, value):
        manifest = self.read(value)
        require(manifest.get('schema') == 'tiplog.f01.study-run.v1'
                and manifest.get('status') == 'passed', 'benchmark study is incomplete')
        reference = {field: manifest[field] for field in BENCHMARK_FIELDS}
        binding = manifest['binding']
        reference.update({field: binding[field] for field in ('plan', 'protocol', 'source_freeze')})
        self.binding(binding)
        for name, expected in manifest['evidence'].items():
            self.bind(name, expected.get('sha256') if isinstance(expected, dict) else expected)
        for field in ('records', 'preflight_records'):
            for name in reference[field]:
                self.record(name)
        for field in ('normalizer_record', 'contract_record'):
            self.record(reference[field])
        for field in ('original_raw', 'raw', 'preflight_raw'):
            for name in reference[field]:
                self.bind(name)
        for field in ('normalization', 'summary', 'contracts', 'plan', 'protocol', 'source_freeze'):
            self.bind(reference[field])
        plan = self.read(reference['plan'])
        for field in ('summarizer', 'contracts'):
            self.bind(plan['analysis'][field], plan['analysis'][field + '_sha256'])
        normalization = self.read(reference['normalization'])
        self.bind(normalization['mapping_plan'], normalization['mapping_plan_sha256'])
        for item in normalization['files']:
            self.bind(item['input'], item['input_sha256'])
            self.bind(item['output'], item['output_sha256'])
            self.record(item['record'])
        return reference

    def assemble(self):
        baseline = self.bind('results/f01/baseline.json')
        freeze = self.bind('results/f01/source-freeze-final.json')
        compatible = [self.bind('results/f01/source-freeze.json')]
        self.bind('results/f01/protocol.json')
        builds = {}
        current_cpp = input_sets(self.root)['cpp']
        for preset in PRESETS:
            choices = []
            for path in sorted((self.root/'results/f01/checks').glob('*.json')):
                saved = read_json(path)
                if (saved.get('status') == 'passed' and saved.get('exit_code') == 0
                        and saved.get('build_provenance', {}).get('preset') == preset
                        and saved['build_provenance'].get('cpp_input_set') == current_cpp):
                    choices.append(path)
            require(choices, 'missing current source-bound full build: '+preset)
            builds[preset] = self.bind(choices[-1].relative_to(self.root).as_posix())
            self.record(builds[preset])
        ctest = {}
        for preset in PRESETS:
            record, _ = self.latest_record(f'final-ctest-{preset}-*.json')
            ctest[preset] = {'record': record,
                             'junit': self.bind(f'results/f01/ctest-{preset}-final.xml')}
        python_record, _ = self.latest_record('final-pytest*.json')
        python = {'record': python_record, 'junit': self.bind('results/f01/python-final.xml')}
        differentials = {}
        for preset in ('release', 'asan-ubsan'):
            index = self.bind(f'results/f01/differential-{preset}.json')
            summary = self.read(index)
            require(summary.get('status') == 'passed', f'incomplete differential index: {index}')
            for name in summary['records']:
                self.record(name)
            differentials[preset] = index
        fuzz_record, record = self.latest_record('final-fuzz-*.json', passed_only=True)
        printed = [json.loads(line) for line in local(self.root, record['log']).read_text().splitlines()
                   if line.startswith('{')]
        require(printed and isinstance(printed[-1].get('summary'), str), 'fuzz launcher omitted summary path')
        fuzz_summary = self.bind(printed[-1]['summary'])
        summary = self.read(fuzz_summary)
        require(summary.get('status') == 'passed', 'fuzz summary is incomplete')
        for target in summary['targets']:
            self.bind(target['argv'][0], target['binary_sha256'])
            self.bind(target['raw_log'], target['raw_log_sha256'])
            # Initial source seeds belong to the source inventory. Generated
            # smoke corpora are deliberately excluded from the artifact set.
        mutations = self.bind('results/f01/contract-mutations-20261027T012413Z/summary.json')
        summary = self.read(mutations)
        require(summary.get('status') == 'passed', 'contract mutation controls are incomplete')
        phase = summary['test_compile']
        self.bind(phase['log'], phase['log_sha256'])
        for control in summary['controls']:
            for phase in control['phases']:
                self.bind(phase['log'], phase['log_sha256'])
        benchmarks = self.benchmarks('results/f01/studies/final-20261027/manifest.json')
        return {
            'schema': SCHEMA, 'status': 'candidate',
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'baseline': baseline, 'source_freeze': freeze,
            'compatible_cpp_freezes': compatible,
            'sources': source_inventory(self.root), 'input_sets': input_sets(self.root),
            'builds': builds,
            'evidence': dict(sorted(self.evidence.items())),
            'validations': {'ctest': ctest, 'python': python, 'differentials': differentials,
                            'fuzz': {'record': fuzz_record, 'summary': fuzz_summary},
                            'benchmarks': benchmarks, 'mutations': mutations},
        }


def destination_path(output, replace):
    path = local(ROOT, str(output))
    require(path.is_relative_to(ROOT / 'results/f01') and path.suffix == '.json',
            'candidate destination must be a JSON file under results/f01')
    if path.exists():
        require(replace, 'candidate already exists; use --replace explicitly')
        require(path.is_file() and read_json(path).get('schema') == SCHEMA,
                '--replace may replace only an existing F-01 acceptance candidate')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'results/f01/acceptance.json')
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args(argv)
    temporary = None
    try:
        output = destination_path(args.output, args.replace)
        candidate = Candidate().assemble()
        require(output.relative_to(ROOT).as_posix() not in candidate['evidence'],
                'candidate destination would overwrite bound evidence')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                         prefix='.' + output.name + '.', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(candidate, indent=2, allow_nan=False) + '\n')
        destination_path(output, args.replace)
        if args.replace:
            os.replace(temporary, output)
        else:
            # Same-directory hard linking atomically refuses an intervening
            # writer instead of silently overwriting a newly created result.
            os.link(temporary, output)
        print(json.dumps({'status': 'candidate', 'output': str(output.relative_to(ROOT)),
                          'evidence_files': len(candidate['evidence'])}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'cannot assemble F-01 acceptance candidate: {error}\n')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
