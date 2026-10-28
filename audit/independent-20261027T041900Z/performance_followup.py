#!/usr/bin/env python3
"""Counterbalanced, CPU-affined follow-up for the retained K64 timing loss."""
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from datetime import datetime, timezone

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_remediation import digest
from run_f01_study import host_observation
import f01_summary as contract


def main():
    original = json.loads((RUN/'evidence/performance-protocol.json').read_text())
    cpu = min(os.sched_getaffinity(0))
    argv = ['--records','4096','--seed','20261027','--cases','no-match','--shapes','small',
            '--partitions','64,256','--candidate-every','1','--modes','indexed','--kernels','stdpq',
            '--budgets','legacy,unlimited,1,32','--schedules','immediate-redrain','--max-outputs','128','--reps','1']
    plan = {'schema':'tiplog-independent-performance-followup-v1','declared_utc':datetime.now(timezone.utc).isoformat(),
            'reason':'Investigate original K64 first-fixture timing loss; preserve all primary observations.',
            'argv':argv,'cpu':cpu,'pairs':10,'order':'initial/final on even pair indexes, final/initial on odd',
            'expected_rows':160,'builds':original['builds'],
            'scope':'Shared host; child-process affinity only, no governor/cache/host-setting changes. Same inputs, output and service policies; no confidence or universal nonregression claim.'}
    plan_path = RUN/'evidence/performance-followup-protocol.json'
    with plan_path.open('x') as stream: json.dump(plan,stream,indent=2); stream.write('\n')
    temporary = ROOT/'build/f01/independent-performance-followup'
    temporary.mkdir(exist_ok=False)
    directory = RUN/'evidence/performance-followup'; directory.mkdir(exist_ok=False)
    records, rows = [], {'initial':{},'final':{}}
    for pair in range(10):
        for kind in (('initial','final') if pair%2 == 0 else ('final','initial')):
            binary = ROOT/plan['builds'][kind]['binary']; sha = plan['builds'][kind]['sha256']
            assert digest(binary) == sha
            raw = temporary/f'{kind}-{pair}.jsonl'
            label = f'performance-control-{kind}-{pair}'
            before = set((RUN/'evidence').glob(label+'-*.json'))
            host_before = host_observation()
            code = subprocess.run([sys.executable,str(RUN/'run_check.py'),label,'--','taskset','-c',str(cpu),
                                   str(binary),*argv,'--output',str(raw)],cwd=ROOT).returncode
            assert code == 0 and digest(binary) == sha
            created = set((RUN/'evidence').glob(label+'-*.json'))-before; assert len(created) == 1
            record = created.pop()
            kept = directory/raw.name; kept.write_bytes(raw.read_bytes())
            data = [contract.decode(line) for line in raw.read_text().splitlines()]; assert len(data) == 8
            for row in data:
                key = contract.validate(row)
                assert (*key,pair) not in rows[kind]
                rows[kind][(*key,pair)] = row
            records.append({'pair':pair,'kind':kind,'record':str(record.relative_to(ROOT)),
                            'binary_sha256':sha,'raw':str(kept.relative_to(ROOT)),'raw_sha256':digest(kept),
                            'host_before':host_before,'host_after':host_observation()})
    assert set(rows['initial']) == set(rows['final']) and len(rows['initial']) == 80
    comparisons = []
    for key in sorted({identity[:-1] for identity in rows['initial']}):
        pairs = [(rows['initial'][(*key,i)],rows['final'][(*key,i)]) for i in range(10)]
        assert all(a['poll_work'] == b['poll_work'] and a['output_digest'] == b['output_digest']
                   and a['calls'] == b['calls'] and a['service_calls'] == b['service_calls'] for a,b in pairs)
        ratios = [b['poll_latency_ns']['sum']/a['poll_latency_ns']['sum'] for a,b in pairs]
        comparisons.append(dict(zip(contract.IDENTITY,key)) | {'paired_ratios':ratios,
            'paired_ratio_median':statistics.median(ratios),'initial_poll_ns_median':statistics.median(a['poll_latency_ns']['sum'] for a,b in pairs),
            'final_poll_ns_median':statistics.median(b['poll_latency_ns']['sum'] for a,b in pairs)})
    result = {'status':'passed','validated_rows':160,'pairs':10,'protocol':str(plan_path.relative_to(ROOT)),
              'protocol_sha256':digest(plan_path),'records':records,'comparisons':comparisons}
    (RUN/'evidence/performance-followup.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','rows':160,'paired_ratio_range':[
        min(x['paired_ratio_median'] for x in comparisons),max(x['paired_ratio_median'] for x in comparisons)]}),flush=True)


if __name__ == '__main__': main()
