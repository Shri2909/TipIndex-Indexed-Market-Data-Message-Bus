#!/usr/bin/env python3
"""Execute the predeclared actual-source comparison; retain all rows/workloads."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import f01_summary as contract
from check_remediation import digest, input_sets
from run_f01_study import host_observation


def main():
    protocol_path = RUN/'evidence/performance-protocol.json'
    plan = json.loads(protocol_path.read_text())
    for name in ('differential-release.json','differential-asan-ubsan.json','fuzz.json'):
        assert json.loads((RUN/'evidence'/name).read_text())['status'] == 'passed'
    baseline = json.loads((RUN/'evidence/layout_tools/baseline-poll-bench-identity.json').read_text())
    assert baseline['source_archive_sha256'] == digest(RUN/'initial/source-snapshot.tar')
    assert baseline['release_flags'] == plan['compiler_flags']
    output = ROOT/'build/f01/independent-performance-20261027'
    output.mkdir(exist_ok=False)
    evidence = RUN/'evidence/performance'; evidence.mkdir(exist_ok=False)
    current_cpp = input_sets(ROOT)['cpp']
    measurements, normalization = [], []
    rows_by_build = {'initial':[], 'final':[]}
    paths_by_build = {'initial':[], 'final':[]}
    for repetition in range(3):
        for kind in ('initial','final'):
            spec = plan['builds'][kind]
            binary = ROOT/spec['binary']
            assert digest(binary) == spec['sha256']
            raw = output/f'{kind}-{repetition}.jsonl'
            label = f'performance-{kind}-{repetition}'
            before = set((RUN/'evidence').glob(label+'-*.json'))
            host_before = host_observation()
            started = datetime.now(timezone.utc).isoformat()
            code = subprocess.run([sys.executable,str(RUN/'run_check.py'),label,'--',str(binary),
                                   *plan['argv'],'--output',str(raw)],cwd=ROOT).returncode
            assert code == 0 and digest(binary) == spec['sha256'] and input_sets(ROOT)['cpp'] == current_cpp
            created = set((RUN/'evidence').glob(label+'-*.json'))-before
            assert len(created) == 1
            record_path = created.pop()
            original = evidence/f'{kind}-{repetition}.original.jsonl'
            original.write_bytes(raw.read_bytes())
            rows = [contract.decode(line) for line in raw.read_text().splitlines()]
            assert len(rows) == plan['expected_rows_per_process']
            normalized = evidence/f'{kind}-{repetition}.normalized.jsonl'
            for row in rows:
                contract.validate(row)
                assert row['repetition'] == 0
                row['repetition'] = repetition
            with normalized.open('x') as stream:
                for row in rows: stream.write(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n')
            rows_by_build[kind].extend(rows); paths_by_build[kind].append(normalized)
            normalization.append({'initial_output':str(raw.relative_to(ROOT)),'original':str(original.relative_to(ROOT)),
                                  'original_sha256':digest(original),'derived':str(normalized.relative_to(ROOT)),
                                  'derived_sha256':digest(normalized),'only_changed_field':'repetition',
                                  'tool_repetition':0,'process_repetition':repetition})
            measurements.append({'kind':kind,'repetition':repetition,'record':str(record_path.relative_to(ROOT)),
                                 'binary_sha256':spec['sha256'],'started_utc':started,
                                 'host_before':host_before,'host_after':host_observation()})
    summaries = {kind:contract.summarize(paths) for kind,paths in paths_by_build.items()}
    for kind,summary in summaries.items():
        assert summary['validated_rows'] == 96 and len(summary['arms']) == 32
        (evidence/(kind+'-summary.json')).write_text(json.dumps(summary,indent=2)+'\n')
    index = {kind:{(*contract.validate(row),row['repetition']):row for row in rows}
             for kind,rows in rows_by_build.items()}
    assert set(index['initial']) == set(index['final']) and len(index['final']) == 96
    comparisons = []
    for initial_arm in summaries['initial']['arms']:
        key = tuple(initial_arm[field] for field in contract.IDENTITY)
        final_arm = next(row for row in summaries['final']['arms'] if tuple(row[f] for f in contract.IDENTITY) == key)
        pairs = [(index['initial'][(*key,r)],index['final'][(*key,r)]) for r in range(3)]
        for a,b in pairs:
            for field in ('output_digest','oracle_digest','final_checkpoint','calls','inspections_used',
                          'poll_work','open_work','all_work','stop_counts','service_calls'):
                assert a[field] == b[field], (key,field)
        comparisons.append(dict(zip(contract.IDENTITY,key)) | {
            'initial_poll_ns':initial_arm['poll_sum_ns_median'],'final_poll_ns':final_arm['poll_sum_ns_median'],
            'paired_poll_ratio':statistics.median(b['poll_latency_ns']['sum']/a['poll_latency_ns']['sum'] for a,b in pairs),
            'initial_open_ns':initial_arm['open_ns_median'],'final_open_ns':final_arm['open_ns_median'],
            'initial_poll_p99_ns':initial_arm['poll_p99_ns_median'],'final_poll_p99_ns':final_arm['poll_p99_ns_median'],
            'initial_drain_ns':initial_arm['drain_elapsed_ns_median'],'final_drain_ns':final_arm['drain_elapsed_ns_median'],
            'initial_drain_cpu_ns':initial_arm['drain_cpu_ns_median'],'final_drain_cpu_ns':final_arm['drain_cpu_ns_median'],
            'initial_peak_rss_max':max(a['peak_rss_bytes'] for a,b in pairs),
            'final_peak_rss_max':max(b['peak_rss_bytes'] for a,b in pairs),
            'calls':initial_arm['calls_median'],'poll_sample_counts':initial_arm['poll_sample_counts'],
            'index_seeks':initial_arm['index_seeks_median'],'paired_repetitions':3})
    result = {'schema':'tiplog-independent-performance-v1','status':'passed','validated_rows':192,
              'protocol':str(protocol_path.relative_to(ROOT)),'protocol_sha256':digest(protocol_path),
              'cpp_input_set':current_cpp,'measurements':measurements,'normalization':normalization,
              'comparisons':comparisons,'interpretation':plan['purpose']}
    (RUN/'evidence/performance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','validated_rows':192,'paired_arm_groups':len(comparisons)}),flush=True)


if __name__ == '__main__': main()
