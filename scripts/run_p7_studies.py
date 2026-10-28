#!/usr/bin/env python3
"""Run the frozen P7 matrix serially, preserving complete and failed attempts."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.file_digest(Path(path).open('rb'), 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('results/raw/P7/studies'))
    parser.add_argument('--cpu', type=int, default=2)
    args = parser.parse_args()
    protocol_path = ROOT / 'results/p7/protocol.json'
    protocol = json.loads(protocol_path.read_text())
    manifest = json.loads(args.manifest.read_text())
    files = manifest['files']
    binary = ROOT / 'build/release/tiplog_layout'
    dependencies = [binary, protocol_path, args.manifest, Path(__file__)]
    dependencies += sorted((ROOT / 'src/tiplog/layout').glob('*.*'))
    dependencies += [ROOT / 'tools/tiplog_layout/main.cpp']
    identities = {str(p.relative_to(ROOT) if p.is_absolute() else p): sha(p) for p in dependencies}
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {'schema': 'tiplog-p7-study-campaign-v1', 'status': 'running',
               'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'protocol': 'results/p7/protocol.json', 'identities': identities,
               'cpu': args.cpu, 'affinity_observer': sorted(os.sched_getaffinity(0)),
               'files': [], 'scope': 'Serial modeled-layout studies, no concurrent P6 measurements/fuzz/builds. Host not exclusive; solver times diagnostic.'}
    summary_path = args.output / 'campaign.json'
    summary_path.write_text(json.dumps(summary, indent=2) + '\n')
    for index, item in enumerate(files):
        input_path = Path(item['path'])
        assert sha(input_path) == item['sha256'], f'input identity: {input_path}'
        label = input_path.stem
        accepted = args.output / f'{label}.accepted.json'
        if accepted.exists():
            record = json.loads(accepted.read_text())
            assert record['identities'] == identities, 'resume identities differ'
            assert sha(record['output']) == record['output_sha256'], 'resume output changed'
            summary['files'].append(record)
            continue
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        prefix = args.output / f'{label}-{stamp}'
        output = Path(str(prefix) + '.jsonl')
        log = Path(str(prefix) + '.log')
        resources = Path(str(prefix) + '.resources.txt')
        command = ['/usr/bin/time', '-v', '-o', str(resources), 'taskset', '-c', str(args.cpu),
                   str(binary), '--input', str(input_path), '--output', str(output),
                   '--methods', ','.join(protocol['methods'])]
        for name, value in protocol['solver_limits'].items():
            command += ['--' + name.replace('_', '-'), str(value)]
        if item['kind'] == 'real':
            command += ['--full-curves']
        record = {'input': str(input_path), 'input_sha256': item['sha256'], 'cases': item['cases'],
                  'kind': item['kind'], 'output': str(output), 'argv': command,
                  'identities': identities, 'started_utc': stamp, 'log': str(log),
                  'resources': str(resources), 'status': 'running'}
        status_path = Path(str(prefix) + '.status.json')
        status_path.write_text(json.dumps(record, indent=2) + '\n')
        before = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        record.update(exit_code=result.returncode, seconds=time.monotonic()-before)
        rows = 0
        errors = []
        if output.exists():
            with output.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    rows += 1
                    if row.get('type') == 'error' or row.get('status') == 'error':
                        errors.append(row)
        expected = item['cases'] * len(protocol['methods'])
        record.update(rows=rows, expected_rows=expected, errors=errors,
                      status='passed' if result.returncode == 0 and rows == expected and not errors else 'failed',
                      output_sha256=sha(output) if output.exists() else None,
                      log_sha256=sha(log), resources_sha256=sha(resources))
        status_path.write_text(json.dumps(record, indent=2) + '\n')
        summary['files'].append(record)
        summary_path.write_text(json.dumps(summary, indent=2) + '\n')
        print(f"{index+1}/{len(files)} {label}: {record['status']}, {rows} rows, {record['seconds']:.1f}s", flush=True)
        if record['status'] != 'passed':
            summary['status'] = 'failed'
            summary_path.write_text(json.dumps(summary, indent=2) + '\n')
            return 1
        accepted.write_text(json.dumps(record, indent=2) + '\n')
    assert all(sha(p) == value for p, value in identities.items()), 'source changed during studies'
    summary.update(status='passed', completed_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   cases=sum(f['cases'] for f in summary['files']), rows=sum(f['rows'] for f in summary['files']))
    summary_path.write_text(json.dumps(summary, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
