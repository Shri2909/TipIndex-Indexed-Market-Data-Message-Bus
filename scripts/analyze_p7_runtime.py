#!/usr/bin/env python3
"""Per-input uncertainty from the accepted controlled P7 process rounds."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def describe(values, case_id):
    if not values:
        return None
    a=np.asarray(values,dtype=float)
    seed=20191230 ^ int(hashlib.sha256(case_id.encode()).hexdigest()[:16],16)
    rng=np.random.default_rng(seed)
    medians=np.median(rng.choice(a,size=(10000,len(a)),replace=True),axis=1)
    low,high=np.quantile(medians,[.025,.975])
    q1,q3=np.quantile(a,[.25,.75])
    return {'n':len(a),'median':float(np.median(a)),'q1':float(q1),'q3':float(q3),
            'iqr':float(q3-q1),'minimum':float(a.min()),'maximum':float(a.max()),
            'ci_low':float(low),'ci_high':float(high),'bootstrap_resamples':10000,'seed':seed}


def main():
    path=Path('results/p7/runtime-campaign.json')
    campaign=json.loads(path.read_text())
    assert campaign['status']=='passed'
    rounds=campaign['rounds']
    assert len(rounds)==11
    measured=[r for r in rounds if r['kind']=='measured']
    warmups=[r for r in rounds if r['kind']=='warmup']
    assert len(measured)==10 and len(warmups)==1
    metadata_path=Path('results/raw/P7/inputs/metadata.json')
    metadata=json.loads(metadata_path.read_text())
    cases={k:v for k,v in metadata['case_index'].items() if v['kind']=='synthetic'}
    assert len(cases)==900
    observations=defaultdict(list)
    frequencies=[]
    identities={str(path):sha(path),str(metadata_path):sha(metadata_path)}
    for record in measured:
        output=Path(record['output'])
        assert sha(output)==record['output_sha256']
        identities[str(output)]=record['output_sha256']
        seen=set()
        for line in output.read_text().splitlines():
            row=json.loads(line);case_id=row['id']
            assert case_id in cases and case_id not in seen and row['method']=='dp'
            assert row['cpu_before']==row['cpu_after']==2
            assert row['ac_before'] is True and row['ac_after'] is True
            assert row['freq_before_khz']>0 and row['freq_after_khz']>0
            seen.add(case_id)
            observations[case_id].append(row)
            frequencies.extend((row['freq_before_khz'],row['freq_after_khz']))
        assert seen==cases.keys()
    frequency_median=statistics.median(frequencies)
    results=[];outcomes=Counter();flagged=0
    for case_id,meta in sorted(cases.items()):
        rows=observations[case_id]
        assert len(rows)==10
        statuses=Counter(row['solver_status'] for row in rows)
        outcomes.update(statuses)
        solved=[r for r in rows if r['status']=='feasible' and r['exact'] and r['solver_status']=='solved']
        flags=sum(any(abs(r[field]-frequency_median)>frequency_median*.1
                      for field in ('freq_before_khz','freq_after_khz')) for r in rows)
        flagged+=flags
        results.append({'id':case_id,'nodes':meta['nodes'],'classes':meta['requested_classes'],
                        'budget':meta['budget'],'shape':meta['shape'],'seed':meta['seed'],
                        'n_measured':len(rows),'n_solved':len(solved),'all_measured_solved':len(solved)==10,
                        'solver_status_counts':dict(statuses),'frequency_flagged_observations':flags,
                        'solved_seconds':describe([r['seconds'] for r in solved],case_id),
                        'states':sorted({r['states'] for r in rows}),'work':sorted({r['work'] for r in rows})})
    summary={'schema':'tiplog-p7-controlled-runtime-summary-v1','status':'passed','cases':results,
             'configuration_count':900,'measured_process_rounds':10,'saved_warmup_process_rounds':1,
             'measured_attempts':9000,'solver_status_counts':dict(outcomes),
             'all_rounds_solved_configurations':sum(r['all_measured_solved'] for r in results),
             'frequency_median_khz':frequency_median,'frequency_flagged_observations':flagged,
             'frequency_flag_policy':'Any boundary >10% from session median; all observations retained.',
             'statistics':'Each fixed case uses10 distinct measured processes. Solved-only summaries explicitly retain cap counts. Bootstrap percentile95% CI of per-case median uses10000 resamples. Different tree seeds are different inputs.',
             'plot_scope':'Only all10-solved cases; group points are medians of per-input medians across available tree seeds, with available/total coverage reported.',
             'limitations':'Nonexclusive laptop; powersave/turbo/SMT unchanged. CIs do not remove host or frequency bias. No physical I/O or engine latency claim.',
             'identities':identities}
    destination=Path('results/derived/layout-runtime.json')
    destination.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:summary[k] for k in ('status','configuration_count','measured_attempts','solver_status_counts','all_rounds_solved_configurations','frequency_flagged_observations')}))


if __name__=='__main__':
    main()
