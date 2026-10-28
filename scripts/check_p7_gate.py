#!/usr/bin/env python3
"""Check P7's actual artifacts; phase acceptance is recorded separately."""
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path


ROOT=Path(__file__).resolve().parent.parent


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def main():
    checks=[];evidence={}
    def check(name,condition,detail=None):
        checks.append({'check':name,'status':'passed' if condition else 'failed','detail':detail})
    def artifact(name):
        p=Path(name);evidence[name]={'sha256':sha(p),'bytes':p.stat().st_size}
        return load(p)
    def command(pattern):
        paths=sorted(Path('results/p7').glob(pattern))
        check('command exists:'+pattern,bool(paths))
        if not paths:return None
        record=artifact(str(paths[-1]))
        check('command passed:'+record['label'],record['status']=='passed' and record['exit_code']==0,record['argv'])
        log=Path(record['log']);evidence[str(log)]={'sha256':sha(log),'bytes':log.stat().st_size}
        return record
    baseline=artifact('results/p7/baseline.json')
    check('Master prompt preserved',sha(baseline['master']['path'])==baseline['master']['sha256'])
    check('Accepted P6 gate preserved',sha(baseline['P6_gate']['path'])==baseline['P6_gate']['sha256'])
    for entry in baseline['core_files']:
        if entry['path']=='CMakeLists.txt':continue
        check('Core dependency unchanged:'+entry['path'],sha(entry['path'])==entry['sha256'])
    for entry in baseline['existing_binaries']:
        check('Core binary unchanged:'+entry['path'],sha(entry['path'])==entry['sha256'])
    for pattern in ('full-release-tests-*.json','full-asan-ubsan-tests-*.json',
                    'final-build-release-*.json','final-build-asan-ubsan-*.json',
                    'final-release-tests-*.json','final-asan-ubsan-tests-*.json','final-python-p7-*.json',
                    'cc5-release-*.json','cc5-asan-ubsan-*.json','worked-example-release-*.json',
                    'worked-example-asan-ubsan-*.json','reporting-exact-ratio-regression-*.json',
                    'final-python-pre-runtime-*.json','cli-boundaries-leak-enabled-*.json',
                    'runtime-smoke-controls-*.json','analyze-full-matrix-no-ratio-mean-*.json',
                    'global-sweep-*.json','controlled-dp-runtime-*.json','runtime-quiescence-2*.json','runtime-analysis-final-*.json',
                    'figures-all-final-*.json','figure-extension-check-final-*.json'):
        command(pattern)
    cc5a=artifact('results/p7/cc5-release.json');cc5b=artifact('results/p7/cc5-asan-ubsan.json')
    check('CC5 release/ASan exact deterministic equality',cc5a==cc5b)
    check('CC5 >=10000 instances/every applicable count/zero mismatches',cc5a['status']=='passed' and cc5a['completed_instances']>=10000 and cc5a['mismatches']==0 and cc5a['exact_count_comparisons']==cc5a['at_most_comparisons']>10000)
    example=artifact('results/p7/worked-example.json')
    check('Worked example cross-build identity',example==artifact('results/p7/worked-example-asan-ubsan.json'))
    expected={'base':5517460497,'km-max':39881491,'km-min':30029491,'enum':30029491,'dp':30029491}
    check('V32 exact waste and finite endpoints',all(next(r for r in example['rows'] if r['method']==m)['waste']==v for m,v in expected.items()) and example['threshold_min']==28648000 and example['threshold_max']==38647999)
    protocol=artifact('results/p7/protocol.json');manifest=artifact('results/p7/input-manifest.json')
    campaign=artifact('results/raw/P7/studies/campaign.json')
    check('Full matrix attempted and completed',campaign['status']=='passed' and campaign['cases']==214668 and campaign['rows']==1073340 and len(campaign['files'])==32)
    declared=datetime.fromisoformat(protocol['declared_utc'])
    for record in campaign['files']:
        started=datetime.strptime(record['started_utc'],'%Y%m%dT%H%M%S.%fZ').replace(tzinfo=timezone.utc)
        check('Predeclared caps/full batch:'+record['input'],declared<started and record['status']=='passed' and record['rows']==record['cases']*5)
        check('Raw batch identity:'+record['output'],sha(record['output'])==record['output_sha256'])
    check('Full generation population',manifest['case_count']==214668 and len(manifest['files'])==32)
    summary=artifact('results/derived/layout-summary.json')
    check('Independent full-row analysis',summary['status']=='analyzed' and not summary['failure_counts'] and summary['observed_cases']==summary['expected_cases']==214668 and summary['rows']==1073340)
    l2_fields=('weighted_read_bytes','weighted_waste_bytes','weighted_read_amplification','weighted_stores_touched','max_waste_bytes','worst_amplification','worst_amplification_floor4096')
    check('L2 metrics incl. stores touched, max waste and 4KiB-floor worst ratio',all(all(k in r for k in l2_fields) for key in ('quality','consumer_quality','exact_cohort_quality','exact_cohort_consumer_quality') for r in summary[key]))
    real_coverage=[r for r in summary['exact_coverage'] if r['kind']=='real']
    check('Per-stratum count/byte/weight coverage',len(real_coverage)==48 and all(r['expected_cases']==r['observed_cases']==8907 and all(k in r for k in ('case_fraction','byte_fraction','active_class_weight_fraction','solver_status_counts')) for r in real_coverage))
    flat=[r for r in summary['quality'] if r['kind']=='real' and r['hierarchy']=='H-flat' and r['workload']=='W0' and r['method']=='base']
    check('H-flat W0 baseline zero waste across beta',len(flat)==3 and all(Fraction(r['weighted_waste_bytes']['exact'])==0 and r['feasible']==8907 for r in flat))
    check('Serialization correction changed no case metrics',artifact('results/p7/analysis-mean-compatibility.json')['status']=='passed')
    global_results=artifact('results/derived/layout-global.json')
    check('All24 nonnegative multiplier strata independently audited',global_results['status']=='passed' and not global_results['failures'] and len(global_results['strata'])==24 and global_results['checks']>0)
    for s in global_results['strata']:
        check('Global certificate preconditions:'+s['label'],s['global_certified']==(s['complete_partitions']==s['partitions']==8907) and all(Fraction(p['lambda'])>=0 and p['certified']==s['global_certified'] for p in s['points']))
        check('Unsupported budget scope:'+s['label'],all(not b['exact'] or (b['best_evaluated_feasible'] is not None and b['lower_bound'] is not None and Fraction(b['lower_bound']['exact'])==Fraction(b['best_evaluated_feasible']['objective']['exact'])) for b in s['budgets']))
    runtime=artifact('results/p7/runtime-campaign.json')
    check('Controlled warmup+10 fresh process rounds',runtime['status']=='passed' and runtime['accepted_rounds']==11 and runtime['accepted_measured_rounds']==10 and runtime['measured_rows']==9000 and runtime['warmup_rows']==900)
    for r in runtime['rounds']:
        check('Validated runtime round:'+str(r['round']),r['status']=='passed' and r['controls_validated'] and r['settle']['complete'] and r['settle']['actual_seconds']>=60 and not r['validation']['errors'] and not r['validation']['bad_child_controls'] and r['validation']['rows']==900)
        check('Runtime raw identity:'+r['output'],sha(r['output'])==r['output_sha256'])
    quiet=artifact('results/p7/runtime-quiescence.json');rule=artifact('results/p7/runtime-quiescence-rule.json')
    declared_rule=datetime.fromisoformat(rule['declared_utc'])
    check('Quiescence rule declared before the accepted campaign',declared_rule<datetime.fromisoformat(runtime['started_utc']))
    check('Predeclared quiescence rule passed for all11 rounds of this campaign',quiet['status']=='passed' and not quiet['failures'] and len(quiet['rounds'])==11 and all(r['status']=='passed' for r in quiet['rounds']) and quiet['campaign_sha256']==sha('results/p7/runtime-campaign.json') and quiet['rule_sha256']==sha('results/p7/runtime-quiescence-rule.json'))
    timing=artifact('results/derived/layout-runtime.json')
    check('All900 per-input uncertainty/censoring rows',timing['status']=='passed' and len(timing['cases'])==900 and timing['measured_attempts']==9000 and all(r['n_measured']==10 and sum(r['solver_status_counts'].values())==10 for r in timing['cases']))
    figures=artifact('results/figures/p7-figures.json')
    check('F14-F18 actual PNG/PDF artifacts',len(figures['figures'])==5 and len(figures['outputs'])==10 and all(sha(p)==h for p,h in figures['outputs'].items()))
    compatibility=artifact('results/p7/figure-extension-compatibility.json')
    check('Accepted P1/P6 results preserved during extension',compatibility['status']=='passed' and not compatibility['failures'] and all(c['status']=='passed' for c in compatibility['checks']))
    for p in ('docs/report/results_layout.md','results/p7/p7-source-map.md','results/p7/independent-design-review.md','results/p6/p7-study.md'):
        path=Path(p);check('Required report/traceability:'+p,path.is_file() and path.stat().st_size>100)
        if path.exists():evidence[p]={'sha256':sha(path),'bytes':path.stat().st_size}
    result={'phase':'P7-verification','status':'passed' if all(c['status']=='passed' for c in checks) else 'failed',
            'checks':checks,'failures':[c for c in checks if c['status']!='passed'],'evidence':evidence,
            'scope':'Executed-artifact and applicability verification. Root additionally reviews reports, figures, source limitations and claims before writing the P7 gate.'}
    Path('results/p7/gate-checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'checks':len(checks),'failures':result['failures']}))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
