import copy
import json
from pathlib import Path
import pytest
from tiplog_py.exp.audit import acceptance, frequency_flags, pilot_cv
from tiplog_py.exp.auto import calibrate
from tiplog_py.exp.matrix import load, arms_for, consumer, w2_readers, write_requests, write_term_dictionary
from tiplog_py.exp.normalize import normalize_gbench
from tiplog_py.exp.run import (aggregate_t2, normalize_actual, digest_requests, publish_commit,
                              read_json, measurement_command_ok)


def test_packed_limit_invalid_outcome_and_error_validation():
    from tiplog_py.exp.oracle import validate
    expected = {'status': 'invalid_config'}
    assert validate({'status':'invalid_config','reason':'cursor limit'}, expected)['status'] == 'passed'
    assert validate({'status':'invalid_config'}, expected)['status'] == 'failed'


def test_micro_normalization_preserves_individuals_and_units():
    raw = {'context': {}, 'benchmarks': [
        {'name':'M1/k64/geometric16/N4194304/BinHeap', 'run_type':'iteration',
         'repetition_index':0, 'cpu_time':4194304, 'real_time':8388608,
         'time_unit':'ns', 'iterations':10, 'outputs_per_iteration':4194304},
        {'name':'M1/x', 'run_type':'aggregate', 'aggregate_name':'median'},
        {'name':'M2/payload_64/P100/zipf1.1/B256/index_off', 'run_type':'iteration',
         'cpu_time':4096, 'real_time':8192, 'time_unit':'us', 'publishes_per_iteration':4096},
        {'name':'M3-seek/B64', 'run_type':'iteration','cpu_time':8192,'real_time':8192,
         'time_unit':'ns','operations_per_iteration':4096},
        {'name':'M3-scan/B256', 'run_type':'iteration','cpu_time':4000,'real_time':8000,
         'time_unit':'ns','operations_per_iteration':1000},
        {'name':'M1/k1/uniform/N1/StdPQ','run_type':'iteration','error_occurred':True,
         'error_message':'hash mismatch'}]}
    rows = normalize_gbench(raw, {'git': {'sha':'a'*40,'dirty':True}, 'environment_path':'env.json'})
    assert len(rows) == 5
    assert rows[0]['item_cpu_ns'] == 1 and rows[0]['item_wall_ns'] == 2
    assert rows[1]['item_cpu_ns'] == 1000 and rows[1]['config']['index_enabled'] is False
    assert rows[2]['exp'] == 'M3' and rows[2]['config']['operation'] == 'seek' and rows[2]['item_cpu_ns'] == 2
    assert rows[2]['seek_ns'] == 2 and 'scan_ns_per_entry' not in rows[2]
    assert rows[3]['scan_ns_per_entry'] == 4 and 'seek_ns' not in rows[3]
    assert rows[4]['status'] == 'crash' and rows[4]['error'] == 'hash mismatch'
    assert all(row['paired_round_id'] is None for row in rows)
    assert rows[0]['config']['cache_treatment'] == 'micro-loop-natural'


def test_pilot_variance_and_repetition_gate():
    constant = [{'cpu_ns':100,'status':'ok','warmup':False} for _ in range(30)]
    assert pilot_cv(constant, limit=.05)['response_required'] is False
    varied = [dict(row, cpu_ns=(10 if index%2 else 1000)) for index,row in enumerate(constant)]
    assert pilot_cv(varied, limit=.05)['response_required'] is True
    with pytest.raises(ValueError): pilot_cv(constant[:29], limit=.05)
    rows = [dict(config_id='x',exp='T1',rep=rep,warmup=rep<0,process_round_id=f'p{rep}',
                 process_pid=100+rep,oracle_validated=True,oracle={'status':'passed'},
                 cpu_start=2,cpu_end=2,status='ok',measurement_command_ok=True) for rep in range(-1,10)]
    assert acceptance(rows)['status'] == 'passed'
    assert acceptance(rows[:-1])['status'] == 'failed'
    rows[-1]['process_pid']=rows[-2]['process_pid']
    assert acceptance(rows)['status'] == 'failed'


def test_frequency_flags_keep_outliers():
    rows = [dict(config_id='x',rep=i,freq_start_khz=value,freq_end_khz=value)
            for i,value in enumerate([1000,1000,1000,2000])]
    flags = frequency_flags(rows)
    assert flags['session_median_khz'] == 1000
    assert flags['flagged_rows'] == 1 and len(flags['annotations']) == 4
    flags = frequency_flags(rows + [dict(config_id='missing',rep=4)])
    assert flags['unknown_rows'] == 1
    assert flags['annotations'][-1]['frequency_noisy'] is None
    group = dict(config_id='group',process_round_id='one',rep=0,warmup=False,
                 frequency_samples_khz=[1000,1000,2000])
    assert frequency_flags([group])['annotations'][0]['frequency_noisy'] is True


def test_auto_uses_only_training_and_freezes_deterministic_tie(tmp_path):
    rows = []
    for rep in range(10):
        for mode,kernel,cpu in [('scan','stdpq',100),('indexed','binheap',10)]:
            rows.append(dict(config_id=mode,comparison_id='state',paired_round_id=str(rep),raw_path='raw',
                             config={'split':'training','mode':mode,'kernel':kernel},warmup=False,status='ok',
                             cpu_ns=cpu,cpu_user_ns=cpu,cpu_sys_ns=0,selected_partitions=4,estimated_index_fraction=.1))
    rows.append(dict(rows[0],config={'split':'held-out'},cpu_ns=10**12))
    artifact = calibrate(rows, {'max_partitions_candidates':[0,4,16], 'max_fraction_candidates':[.05,.1,.5]},tmp_path/'auto.json')
    assert artifact['policy']['max_partitions'] == 4 and artifact['policy']['max_fraction'] == .1
    assert artifact['evaluation_rows_used'] == 0 and artifact['training_rows'] == 20


def test_t2_group_sum_requires_each_seeded_reader():
    rows = []
    for reader in range(2):
        rows.append(dict(exp='T2',config={'reader_count':2,'reader_index':reader,'mode':'indexed',
                                        'kernel':'binheap','cache_treatment':'repeat-warm','C':1024,'B':64,
                                        'market_seconds':10,'backlog_seconds':10},
                         status='ok',oracle={'status':'passed'},out_count=3,wall_ns=20,cpu_ns=10,
                         cpu_user_ns=9,cpu_sys_ns=1,work={'records_fetched':4,'delivered':3},
                         out_digest={'seq_sha256':str(reader)},oracle_digest={'seq_sha256':str(reader)},
                         seq_sha256=str(reader),payload_sha256=str(reader),sink64=reader,
                         payload_bytes=11+reader,effective_mode='scan' if reader else 'indexed',
                         reader_validation_rows_reference='reader-runs.jsonl'))
    group = aggregate_t2(rows)[0]
    assert group['cpu_ns'] == 20 and group['out_count'] == 6 and group['work']['records_fetched'] == 8
    assert group['status'] == 'ok' and group['config']['R'] == 2
    assert group['out_digest'] is None and group['oracle_digest'] is None
    assert group['seq_sha256'] is None and group['payload_sha256'] is None and group['sink64'] is None
    assert group['reader_validation'] == {'expected_readers':2,'observed_readers':2,
                                          'all_validated':True,'rows_reference':'reader-runs.jsonl'}
    assert group['payload_bytes'] == 23 and group['effective_mode'] == 'mixed'
    assert group['effective_mode_counts'] == {'indexed':1,'scan':1}
    assert group['selected_partitions'] is None and group['estimated_entries'] is None
    assert aggregate_t2(rows[:1])[0]['status'] == 'crash'


def test_subscriptions_overlap_normalization_and_manifest_defaults(tmp_path):
    config = load(Path(__file__).resolve().parents[2] / 'configs/P6/matrix.toml')
    assert config['t3']['partitions'] == [10,1000,100000]
    assert config['t3']['zipf'] == [0,.8,1.2] and config['t3']['run_lengths'] == [1,16,256]
    assert config['t2']['readers'] == [1,10,100,1000]
    assert config['t5']['block_entries'] == [64,256,1024,4096]
    terms = consumer('BOOK',['A','A'])
    assert terms.count('subtree:itch/_market') == 1 and terms.count('subtree:itch/A/add') == 1
    specs = w2_readers(['A','B'],100,31)
    assert specs == w2_readers(['A','B'],100,31)
    arms = arms_for(dict(exp='T3',terms='subtree:synth/p0',after_seq=0,readers=1))
    assert len(arms) == 18
    assert len({row['comparison_id'] for row in arms}) == 2
    path = tmp_path/'requests.tsv'
    write_requests(path,arms)
    assert len(path.read_text().splitlines()) == 19


def test_memory_snapshot_captures_independent_head_without_history_request():
    class IndependentSnapshot:
        rows = list(range(123))
        def expected(self,after_seq,terms,mode):
            assert after_seq == len(self.rows)
            assert terms == 'subtree:itch' and mode == 'scan'
            return {'status':'ok','out_count':0}
    workload = {'requests':[dict(id='snapshot',exp='T5',checkpoint_at_snapshot_head=True,
                                 terms='subtree:itch',mode='scan')]}
    assert digest_requests(workload,IndependentSnapshot())['snapshot']['status'] == 'ok'
    assert workload['requests'][0]['after_seq'] == 123


def test_pending_process_journal_recovery_is_idempotent(tmp_path):
    rows = [dict(process_round_id='r0-attempt0',config_id=name,status='ok') for name in ('a','b')]
    # Simulate interruption after the first append, before state/marker commit.
    (tmp_path/'runs.jsonl').write_text(json.dumps(rows[0])+'\n')
    marker = tmp_path/'process.commit.json'
    payload = {'status':'pending','collections':{'runs.jsonl':rows},
               'completion':{'id':'r0-attempt0','rep':0,'workload_id':'fixture'}}
    state = {'status':'running','completed_processes':[]}
    identities = {}
    publish_commit(tmp_path,marker,payload,state,identities)
    publish_commit(tmp_path,marker,read_json(marker),state,identities)
    assert [json.loads(line) for line in (tmp_path/'runs.jsonl').read_text().splitlines()] == rows
    assert len(state['completed_processes']) == 1
    assert read_json(marker)['status'] == 'committed'


def test_completed_output_does_not_hide_ac_or_process_failure():
    good = {'returncode':0,'before':{'power':{'ac_online':True}},
            'after':{'power':{'ac_online':True}},'observations':[{'power':{'ac_online':True}}]}
    assert measurement_command_ok(good)
    assert not measurement_command_ok(dict(good,returncode=-15))
    assert not measurement_command_ok(dict(good,after={'power':{'ac_online':False}}))
    assert not measurement_command_ok(dict(good,observations=[{'power':{'ac_online':None}}]))


def test_request_dictionary_keeps_full_terms_once_and_exact_alias_binding(tmp_path):
    import hashlib
    terms = 'subtree:synth/p0;exact:synth/p1/e0'
    rows = [dict(id=str(i),exp='functional',terms=terms,after_seq=0,mode='scan',kernel='stdpq',
                 cache_treatment='repeat-warm') for i in range(3)]
    dictionary,requests = tmp_path/'dictionary.tsv',tmp_path/'requests.tsv'
    aliases = write_term_dictionary(dictionary,rows)
    identity = hashlib.sha256(terms.encode()).hexdigest()
    assert aliases == {terms:identity}
    assert dictionary.read_text() == identity+'\t'+terms+'\n'
    write_requests(requests,rows,term_aliases=aliases)
    assert requests.read_text().count('@'+identity) == 3
    assert terms not in requests.read_text()
    assert write_term_dictionary(dictionary,rows) == aliases
    dictionary.write_text('different\n')
    with pytest.raises(ValueError,match='differs'): write_term_dictionary(dictionary,rows)
