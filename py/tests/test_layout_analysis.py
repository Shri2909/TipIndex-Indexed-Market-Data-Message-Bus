"""Adversarial reporting checks: missing output, coverage, feasible cohorts."""
from fractions import Fraction
import pytest

from tiplog_py.layout.analyze import Analyzer, distribution
from tiplog_py.layout.global_study import validate_observation_rows


def test_global_sweep_requires_all_rows_once():
    rows = [dict(type='global_point',lambda_='0')]
    rows[0]['lambda']='0'
    rows += [dict(type='global_budget_bound',budget=2,**{'lambda':'0'})]
    validate_observation_rows(rows,['0'],[2])
    for invalid in ([],rows[:1],rows+[rows[0]],rows+[dict(type='error',**{'lambda':'0'})]):
        with pytest.raises(ValueError):
            validate_observation_rows(invalid,['0'],[2])
    with pytest.raises(ValueError):
        validate_observation_rows(rows,['0','1'],[2])


def fixture_metadata():
    classes={'effective_classes':[{'name':'BOOK','weight':'1','members':[0]}],
             'raw_classes':[{'name':'BOOK','weight':'1'}],'active_class_weight':'1'}
    case=dict(kind='real',source_kind='real_itch',hierarchy='H-spec',workload='W1',alpha='1',beta=0,gamma=0,
              budget_policy='baseline',budget=2,nodes=3,positive_nodes=2,total_bytes=5,classes_metadata_key='same')
    return {'case_index':{'solved':dict(case),'capped':dict(case)},'partition_workloads':{'same':classes}}


def row(case,method,solved=True,feasible=True):
    exact=method in ('enum','dp') and solved
    if method in ('enum','dp') and not solved:
        return dict(type='layout',id=case,method=method,budget=2,nodes=3,classes=1,total_bytes=5,
                    stores=None,states=1,work=1,scale='1',objective=None,exact=False,status='state_limit',
                    solver_status='state_limit',seconds=.001,complete_domain=False,curve=[None,None,None])
    return dict(type='layout',id=case,method=method,budget=2,nodes=3,classes=1,total_bytes=5,stores=2,
                states=1,work=1,scale='1',objective='2',exact=exact,status='feasible' if feasible else 'infeasible_budget',
                solver_status='solved' if exact else 'constructed',seconds=.001,read_bytes=[2],useful_bytes=[2],
                waste_bytes=[0],stores_touched=[1],curve=[None,'5','2'],complete_domain=exact)


def test_partial_coverage_uses_identical_feasible_exact_cohort():
    a=Analyzer(fixture_metadata())
    methods=('base','km-min','km-max','enum','dp')
    a.process_case('solved',[row('solved',m) for m in methods])
    a.process_case('capped',[row('capped',m,solved=False) for m in methods])
    out=a.finish()
    assert not out['failure_counts']
    coverage=out['exact_coverage'][0]
    assert coverage['case_fraction']==coverage['byte_fraction']==coverage['active_class_weight_fraction']==Fraction(1,2)
    full_base=next(r for r in out['quality'] if r['method']=='base')
    cohort_base=next(r for r in out['exact_cohort_quality'] if r['method']=='base')
    assert full_base['objective']==4 and cohort_base['objective']==2
    assert len(out['exact_cohort_quality'])==4
    for r in out['exact_cohort_consumer_quality']:
        assert r['class_observations']==1 and r['weighted_read_bytes']==2
        assert 'objective' not in r and 'stores' not in r
    comparison=next(r for r in out['comparisons'] if r['method']=='base')
    assert comparison['same_budget_exact_comparisons']==1
    assert comparison['gap_status_counts']['no_agreed_certified_same_budget_optimum']==1


def test_infeasible_baseline_never_enters_comparable_cohort():
    meta=fixture_metadata();meta['case_index']={'solved':meta['case_index']['solved']}
    meta['case_index']['solved']['budget']=1
    a=Analyzer(meta)
    rows=[row('solved',m,feasible=(m!='base')) for m in ('base','km-min','km-max','enum','dp')]
    for r in rows:
        r['budget']=1
        if r['method']!='base':
            r.update(stores=1,objective='5',read_bytes=[5],waste_bytes=[3])
    a.process_case('solved',rows)
    result=a.finish()
    assert not result['failure_counts']
    assert result['exact_cohort_quality']==[] and result['exact_cohort_consumer_quality']==[]
    base=next(r for r in result['quality'] if r['method']=='base')
    assert base['objective'] is None and base['stores'] is None


def test_gap_quartiles_and_empty_schema():
    from collections import Counter
    d=distribution(Counter({Fraction(0):1,Fraction(1):1,Fraction(2):1,Fraction(3):1}))
    assert (d['p25'],d['median'],d['p75'])==(0,1,2)
    assert distribution(Counter())['p25'] is None


def test_many_distinct_ratio_denominators_do_not_require_a_huge_exact_mean():
    from collections import Counter
    import json
    from tiplog_py.layout.analyze import json_exact
    values=Counter(Fraction(1,10**110+i) for i in range(1,81))
    result=json_exact(distribution(values))
    assert result['count']==80 and 'mean' not in result
    assert json.loads(json.dumps(result))['median']['exact']
