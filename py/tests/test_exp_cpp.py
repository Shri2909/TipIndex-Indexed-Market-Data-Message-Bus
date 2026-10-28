"""Reduced functional CC-4 comparisons against a separate Python oracle.

These subprocess timings are test diagnostics, never experiment observations.
The independent schedule, retention model and digest construction are exercised
together with the production executable, including wrap/expiry and empty ranges.
"""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from tiplog_py.exp.hashes import build_accelerator
from tiplog_py.exp.matrix import write_requests, write_term_dictionary
from tiplog_py.exp.oracle import OutcomeOracle, digest_selection, validate
from tiplog_py.exp.run import validate_synthetic_summary
from tiplog_py.exp.synthetic import empirical_mix, schedule, schedule_summary

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / 'build/release/tiplog_bench'


@pytest.fixture(scope='module', autouse=True)
def byte_accelerator():
    if not BINARY.exists():
        pytest.skip('release tiplog_bench must be built for functional integration')
    build_accelerator()


@pytest.mark.parametrize('partitions', [10, 1000])
@pytest.mark.parametrize('zipf', [0.0, .8, 1.2])
@pytest.mark.parametrize('run_length', [1, 16, 256])
@pytest.mark.parametrize('capacity', [2048, 262144])
def test_cpp_schedule_outcomes_and_digests(tmp_path, partitions, zipf, run_length, capacity):
    options = dict(records=2048, partitions=partitions, zipf=zipf,
                   run_length=run_length, seed=20191231,
                   mix=empirical_mix(ROOT/'configs/m2_payload_mix.csv'))
    data, rows, topics = schedule(**options)
    source = SimpleNamespace(data=data, rows=rows, topics=topics)
    oracle = OutcomeOracle(source, capacity)
    requests = []
    for terms in ('subtree:synth', 'subtree:synth/p0',
                  'exact:synth/p0/e0;exact:synth/p0/e1', 'exact:synth/p999999/e9'):
        for after in (0, 2040, 3000):
            for mode, kernel in [('scan','stdpq')] + [(mode,kernel)
                    for mode in ('indexed','auto')
                    for kernel in ('stdpq','binheap','quad','loser')]:
                requests.append(dict(id=str(len(requests)), exp='functional-CC4',
                                     after_seq=after, terms=terms, mode=mode,
                                     kernel=kernel, cache_treatment='repeat-warm', batch=7))
    request_path, output = tmp_path/'requests.tsv', tmp_path/'actual.jsonl'
    dictionary = tmp_path/'terms.tsv'
    aliases = write_term_dictionary(dictionary,requests)
    write_requests(request_path, requests,term_aliases=aliases)
    subprocess.run([str(BINARY), '--synthetic', '--records','2048',
                    '--partitions',str(partitions), '--zipf',str(zipf),
                    '--run-length',str(run_length), '--seed','20191231',
                    '--ring-bytes',str(capacity), '--block-entries','64',
                    '--requests',str(request_path),'--term-dictionary',str(dictionary),'--output',str(output)],
                   cwd=ROOT, check=True, capture_output=True, text=True, timeout=90)
    actual = [json.loads(line) for line in output.read_text().splitlines()]
    prefill = actual.pop(0)
    expected_prefill = digest_selection(data, rows, np.arange(len(rows), dtype=np.int64))
    assert prefill['publications'] == expected_prefill['out_count']
    assert prefill['publish_sink64'] == expected_prefill['sink64']
    validate_synthetic_summary(prefill, {'kind':'synthetic',
                               'synthetic_summary':schedule_summary(rows, partitions)})
    assert prefill['pressure_data_evicted'] == 0
    for key in ('head_pos','tail_pos','head_seq','tail_seq'):
        assert prefill[key] == oracle.layout[key]
    by_id = {row['id']:row for row in actual}
    assert len(by_id) == len(requests)
    for request in requests:
        expected = oracle.expected(request['after_seq'], request['terms'], mode=request['mode'])
        check = validate(by_id[request['id']], expected)
        assert check['status'] == 'passed', (request, check)


def test_cpp_packed_limit_rejects_indexed_and_auto_falls_back(tmp_path):
    partitions, capacity = 100000, 262144
    data, rows, topics = schedule(records=128, partitions=partitions, zipf=1.2,
                                 run_length=16, seed=20191231,
                                 mix=empirical_mix(ROOT/'configs/m2_payload_mix.csv'))
    oracle = OutcomeOracle(SimpleNamespace(data=data, rows=rows, topics=topics), capacity)
    terms = ';'.join(f'subtree:synth/p{owner}' for owner in range(partitions))
    requests = [dict(id=str(index), exp='functional-packed-limit', after_seq=0,
                     terms=terms, mode=mode, kernel=kernel,
                     cache_treatment='repeat-warm', batch=7)
                for index,(mode,kernel) in enumerate([('scan','stdpq')] +
                    [(mode,kernel) for mode in ('indexed','auto')
                     for kernel in ('stdpq','binheap','quad','loser')])]
    request_path, output = tmp_path/'requests.tsv', tmp_path/'actual.jsonl'
    dictionary = tmp_path/'terms.tsv'
    aliases = write_term_dictionary(dictionary,requests)
    write_requests(request_path, requests,term_aliases=aliases)
    subprocess.run([str(BINARY),'--synthetic','--records','128','--partitions',str(partitions),
                    '--zipf','1.2','--run-length','16','--seed','20191231',
                    '--ring-bytes',str(capacity),'--block-entries','64',
                    '--requests',str(request_path),'--term-dictionary',str(dictionary),'--output',str(output)],
                   cwd=ROOT, check=True, capture_output=True, text=True, timeout=180)
    actuals = [json.loads(line) for line in output.read_text().splitlines()][1:]
    assert len(actuals) == len(requests)
    for actual,request in zip(actuals,requests):
        expected = oracle.expected(0, terms, mode=request['mode'])
        assert validate(actual,expected)['status'] == 'passed', actual
        assert actual['status'] == ('invalid_config' if request['mode'] == 'indexed' else 'ok')
        if request['mode'] == 'auto': assert actual['effective_mode'] == 'scan'


def test_cpp_term_dictionary_plain_alias_equivalence_and_rejections(tmp_path):
    terms = 'subtree:synth/p0;exact:synth/p1/e0'
    requests = [dict(id='selection',exp='functional-alias',after_seq=0,terms=terms,
                     mode='indexed',kernel='binheap',cache_treatment='repeat-warm',batch=7)]
    dictionary = tmp_path/'terms.tsv'
    aliases = write_term_dictionary(dictionary,requests)
    base = [str(BINARY),'--synthetic','--records','128','--partitions','10',
            '--zipf','.8','--run-length','16','--seed','20191231',
            '--ring-bytes','262144','--block-entries','64']
    answers = []
    for alias in (False,True):
        request_path,output = tmp_path/f'requests-{alias}.tsv',tmp_path/f'actual-{alias}.jsonl'
        write_requests(request_path,requests,term_aliases=aliases if alias else None)
        command = base+['--requests',str(request_path),'--output',str(output)]
        if alias: command += ['--term-dictionary',str(dictionary)]
        subprocess.run(command,cwd=ROOT,check=True,capture_output=True,text=True,timeout=30)
        answers.append(json.loads(output.read_text().splitlines()[1]))
    for key in ('status','out_count','seq_sha256','payload_sha256','sink64','checkpoint',
                'error','upper_seq','upper_pos','effective_mode','work'):
        assert answers[0][key] == answers[1][key]
    request_path = tmp_path/'missing-alias.tsv'
    write_requests(request_path,requests,term_aliases={terms:'0'*64})
    output = tmp_path/'missing-alias.jsonl'
    subprocess.run(base+['--requests',str(request_path),'--term-dictionary',str(dictionary),
                        '--output',str(output)],cwd=ROOT,check=True,capture_output=True,text=True,timeout=30)
    rejected = json.loads(output.read_text().splitlines()[1])
    assert rejected['status'] == 'invalid_config' and rejected['reason']
    # Incorrect content binding and duplicate dictionary keys are process-level
    # setup errors, before the benchmark can accept any observations.
    for index,text in enumerate(['0'*64+'\t'+terms+'\n',dictionary.read_text()*2]):
        bad = tmp_path/f'bad-dictionary{index}.tsv';bad.write_text(text)
        child = subprocess.run(base+['--requests',str(request_path),'--term-dictionary',str(bad),
                                     '--output',str(tmp_path/f'bad-output{index}.jsonl')],
                               cwd=ROOT,capture_output=True,text=True,timeout=30)
        assert child.returncode != 0 and child.stderr
