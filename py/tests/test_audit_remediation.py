"""Regression contracts for the approved independent audit remediation."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess

import numpy as np
import pytest

from tiplog_py.exp.audit import acceptance
from tiplog_py.exp.oracle import TraceIndex, retained_layout, validate
from tiplog_py.exp.run import aggregate_t2, publish_commit, read_json
from tiplog_py.exp.synthetic import schedule
from tiplog_py.itch.__main__ import main
from tiplog_py.itch.protocol import BinaryFileReader, FramingError, LENGTHS, SYMBOL_OFFSETS
from tiplog_py.trace import TraceReader, TraceWriter
from tiplog_py.trace.format import TraceError, path_bytes


def binary_source(path):
    payload = b'S' + bytes(10) + b'O'
    path.write_bytes(struct.pack('>H', len(payload)) + payload + b'\0\0')
    return path.read_bytes()


@pytest.mark.parametrize('kind', sorted(SYMBOL_OFFSETS))
def test_empty_symbol_is_typed_at_absolute_frame_offset(kind):
    prefix = b'\0\x0cS' + bytes(10) + b'O'
    payload = bytearray(LENGTHS[kind]); payload[0] = ord(kind)
    start = SYMBOL_OFFSETS[kind]; payload[start:start+8] = b' '*8
    data = prefix + len(payload).to_bytes(2, 'big') + payload + b'\0\0'
    with pytest.raises(FramingError, match='empty stock symbol') as failure:
        list(BinaryFileReader(io.BytesIO(data), chunk_size=3))
    assert failure.value.offset == len(prefix) + 2


@pytest.mark.parametrize('command', ['measure', 'convert'])
@pytest.mark.parametrize('alias', ['same', 'symlink', 'hardlink', 'csv'])
def test_every_output_preserves_source_aliases(tmp_path, command, alias):
    path = tmp_path/'source.bin'; original = binary_source(path)
    output = tmp_path/'output'
    args = [command, str(path), '--output', str(output)]
    if alias == 'same':
        args[3] = str(path)
    elif alias in ('symlink', 'hardlink'):
        output.symlink_to(path) if alias == 'symlink' else os.link(path, output)
    else:
        table = tmp_path/'tables'/'itch_20191230_window_topic_volumes.csv'
        table.parent.mkdir(); os.link(path, table)
        args += ['--volumes-dir', str(table.parent)]
    with pytest.raises(ValueError, match='preserve the source'):
        main(args)
    assert path.read_bytes() == original
    assert not list(tmp_path.rglob('.*.partial'))


def test_predictable_partial_names_are_never_opened_or_deleted(tmp_path):
    source = tmp_path/'output.mdt.partial'; original = binary_source(source)
    primary = tmp_path/'output.mdt'
    # A second final may have a historical .partial spelling safely: staging is unique.
    second = tmp_path/'output.mdt.partial'
    assert main(['convert', str(source), '--output', str(primary)]) == 0
    assert second.read_bytes() == original
    assert source.read_bytes() == original
    with TraceReader(primary) as reader:
        assert reader.record_count == 0


def test_dual_outputs_may_use_old_other_temporary_spelling(tmp_path):
    source = tmp_path/'source.bin'; original = binary_source(source)
    first = tmp_path/'first.mdt'; second = tmp_path/'first.mdt.partial'
    assert main(['convert',str(source),'--output',str(first),'--also-flat',str(second)]) == 0
    with TraceReader(first) as a, TraceReader(second) as b:
        assert a.record_count == b.record_count == 0
    assert source.read_bytes() == original


@pytest.mark.parametrize('failure', ['second_init', 'second_finish', 'metadata', 'publish', 'backup'])
def test_conversion_failures_keep_existing_bundle_and_owned_cleanup(tmp_path, monkeypatch, failure):
    import tiplog_py.itch.__main__ as cli
    import tiplog_py._outputs as outputs
    source = tmp_path/'source.bin'; original = binary_source(source)
    first, second = tmp_path/'first.mdt', tmp_path/'second.mdt'
    finals = [first, second, Path(str(first)+'.meta.json'), Path(str(second)+'.meta.json')]
    for index, path in enumerate(finals): path.write_bytes(f'old-{index}'.encode())
    before = {path:path.read_bytes() for path in finals}
    sentinel = tmp_path/'first.mdt.partial'; sentinel.write_bytes(b'not-owned')
    if failure in ('second_init', 'second_finish'):
        base = cli.TraceWriter
        class FailingWriter(base):
            count_init = 0
            def __init__(self, *args):
                type(self).count_init += 1
                if failure == 'second_init' and self.count_init == 2:
                    raise OSError('injected writer init failure')
                super().__init__(*args)
                self.second = self.count_init == 2
            def finish(self):
                if failure == 'second_finish' and self.second:
                    raise OSError('injected writer finish failure')
                super().finish()
        monkeypatch.setattr(cli, 'TraceWriter', FailingWriter)
    elif failure == 'metadata':
        monkeypatch.setattr(cli, '_write_json', lambda *_: (_ for _ in ()).throw(OSError('injected metadata failure')))
    else:
        original_replace = outputs.os.replace
        failed = False
        def replace(src, dst):
            nonlocal failed
            is_publish = Path(dst) == second and Path(src) != second
            is_backup = Path(src) == second
            if not failed and (is_publish if failure == 'publish' else is_backup):
                failed = True
                raise OSError('injected rename failure')
            original_replace(src, dst)
        monkeypatch.setattr(outputs.os, 'replace', replace)
    with pytest.raises(OSError, match='injected'):
        main(['convert',str(source),'--output',str(first),'--also-flat',str(second)])
    assert source.read_bytes() == original
    assert {path:path.read_bytes() for path in finals} == before
    assert sentinel.read_bytes() == b'not-owned'
    assert not list(tmp_path.rglob('.*.partial'))


def journal_fixture(tmp_path):
    rows = [dict(process_round_id='p',config_id=name,status='ok',text='snowman ☃') for name in ('a','b')]
    payload = {'status':'pending','collections':{'runs.jsonl':rows},'collection_offsets':{'runs.jsonl':0},
               'completion':{'id':'p'}}
    marker = tmp_path/'process.commit.json'
    marker.write_text(json.dumps(payload))
    return rows, payload, marker


def encoded(row):
    return (json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode()


def test_journal_recovers_every_byte_boundary_exactly_once(tmp_path):
    rows, payload, marker = journal_fixture(tmp_path)
    data = b''.join(encoded(row) for row in rows)
    for cut in range(len(data)+1):
        case = tmp_path/str(cut); case.mkdir()
        marker = case/'process.commit.json'; marker.write_text(json.dumps(payload))
        path = case/'runs.jsonl'; path.write_bytes(data[:cut])
        state = {'completed_processes':[]}; identities = {}
        publish_commit(case,marker,copy.deepcopy(payload),state,identities)
        publish_commit(case,marker,read_json(marker),state,identities)
        assert path.read_bytes() == data
        assert len(state['completed_processes']) == 1
        committed = read_json(marker)
        for recovery in committed['recovered_tails']:
            assert Path(recovery['preserved_path']).read_bytes() == data[recovery['offset']:cut]


@pytest.mark.parametrize('corrupt', [b'{bad}\n', b'{bad}\n{}', b'\xff', b'\n'])
def test_journal_rejects_unowned_or_interior_corruption(tmp_path, corrupt):
    rows, payload, marker = journal_fixture(tmp_path)
    path = tmp_path/'runs.jsonl'; content = encoded(rows[0])+corrupt
    path.write_bytes(content)
    with pytest.raises(ValueError, match='corrupt committed'):
        publish_commit(tmp_path,marker,payload,{'completed_processes':[]},{})
    assert path.read_bytes() == content and read_json(marker)['status'] == 'pending'


def test_journal_append_failure_can_retry_same_process(tmp_path, monkeypatch):
    import tiplog_py.exp.run as runner
    rows, payload, marker = journal_fixture(tmp_path)
    original = runner.append
    def interrupted(path, fresh):
        path.write_bytes(encoded(fresh[0])+encoded(fresh[1])[:15])
        raise OSError('disk full')
    identities = {}; state = {'completed_processes':[]}
    monkeypatch.setattr(runner,'append',interrupted)
    with pytest.raises(OSError,match='disk full'):
        publish_commit(tmp_path,marker,payload,state,identities)
    monkeypatch.setattr(runner,'append',original)
    publish_commit(tmp_path,marker,payload,state,identities)
    assert (tmp_path/'runs.jsonl').read_bytes() == b''.join(map(encoded,rows))


def test_pad_application_has_linear_element_work(monkeypatch):
    work = 0
    class Tracked(np.ndarray):
        def __setitem__(self,key,value):
            nonlocal work
            work += np.asarray(self[key]).size
            return super().__setitem__(key,value)
    cumsum = np.cumsum
    monkeypatch.setattr(np,'cumsum',lambda *a,**k: cumsum(*a,**k).view(Tracked))
    count = 2000
    result = retained_layout(np.full(count,24,dtype='u8'),64)
    assert result['pad_items'] == count//2-1
    assert work <= 3*count
    assert result['head_pos'] == count*24+(count//2-1)*16


@pytest.mark.parametrize('length', [65512,65513,65535])
def test_full_payload_range_and_old_index_cache_rebuild(tmp_path,length):
    path = tmp_path/'wide.mdt'
    with TraceWriter(path,'00'*32) as writer: writer.append('itch/A',b'x'*length,1)
    with TraceReader(path) as reader: assert len(next(iter(reader)).payload) == length
    with TraceIndex(path,tmp_path/'cache') as source:
        expected = (16+length+7)&~7
        assert int(source.rows['size'][0]) == expected
        metadata = source.metadata_path
        data = json.loads(metadata.read_text()); data['parser_version']=1
        metadata.write_text(json.dumps(data))
    with TraceIndex(path,tmp_path/'cache') as source:
        assert source.rows.dtype['size'].itemsize == 4
        assert json.loads(metadata.read_text())['parser_version'] == 2
        assert retained_layout(source.rows['size'],262144)['head_pos'] == expected
    _data, rows, _topics = schedule(records=1,partitions=2,zipf=0,run_length=1,seed=1,mix=[(length,1)])
    assert int(rows['size'][0]) == expected
    checker = Path(__file__).resolve().parents[2]/'build/release/tiplog_trace_check'
    if checker.is_file(): subprocess.run([str(checker),str(path)],check=True,capture_output=True)


def t2_rows(duration):
    return [dict(exp='T2',config={'reader_count':2,'reader_index':i,'mode':'indexed','kernel':'binheap',
                 'cache_treatment':'repeat-warm','C':1024,'B':64,'market_seconds':duration,
                 'backlog_seconds':duration},status='ok',oracle={'status':'passed'},
                 cpu_ns=duration*10**9,cpu_user_ns=duration*10**9,cpu_sys_ns=0,
                 publish_index_on_cpu_ns=4*10**9,publish_index_off_cpu_ns=2*10**9,
                 publish_window_market_seconds=duration) for i in range(2)]


@pytest.mark.parametrize('duration',[1,10,20,60])
def test_t2_preserves_market_duration_and_writer_rate(duration):
    from tiplog_py.analysis.summarize import numeric_metrics
    group = aggregate_t2(t2_rows(duration))[0]
    assert group['config']['market_seconds'] == duration
    metrics = numeric_metrics(group)
    assert metrics['cpu_per_market_second'] == 2
    assert metrics['adjusted_cpu_per_market_second'] == pytest.approx(2+2/duration)
    other = aggregate_t2(t2_rows(duration+1))[0]
    assert group['comparison_id'] != other['comparison_id']


@pytest.mark.parametrize('field,value',[('market_seconds',20),('C',2048),('anchor_ts',50)])
def test_t2_rejects_disagreeing_reader_workloads(field,value):
    rows = t2_rows(10); rows[1]['config'][field]=value
    with pytest.raises(ValueError,match='disagree'):
        aggregate_t2(rows)


def control_rows():
    return [dict(config_id='x',exp='T1',rep=rep,warmup=rep<0,process_round_id=f'p{rep}',
                 process_pid=100+rep,oracle_validated=True,oracle={'status':'passed'},
                 cpu_start=2,cpu_end=2,status='ok',measurement_command_ok=True) for rep in range(-1,10)]


@pytest.mark.parametrize('control',[None,False,'absent'])
def test_acceptance_requires_explicit_command_controls(control):
    rows = control_rows()
    if control == 'absent': rows[0].pop('measurement_command_ok')
    else: rows[0]['measurement_command_ok']=control
    assert acceptance(rows)['status'] == 'failed'


def test_acceptance_names_scope_and_checks_manifest_and_repetitions():
    rows = control_rows(); plan = {'x':list(range(10))}
    result = acceptance(rows)
    assert result['status']=='passed' and result['scope']=='supplied-rows-only'
    assert result['campaign_coverage_verified'] is False
    assert acceptance(rows,expected_manifest=plan)['campaign_coverage_verified'] is True
    result = acceptance(rows,expected_manifest=dict(plan,missing=list(range(10))))
    assert result['status']=='failed' and result['missing_configurations']==['missing']
    rows[-1]['rep']=8
    assert acceptance(rows,expected_manifest=plan)['status']=='failed'
    rows[-1]['rep']=100
    assert acceptance(rows,expected_manifest=plan)['status']=='failed'


def test_internal_benchmark_errors_are_never_invalid_configuration_success():
    for status in ('runtime_error','validation_failure'):
        assert validate({'status':status,'reason':'failure'},{'status':'invalid_config'})['status']=='failed'


def test_figure_source_identity_does_not_depend_on_working_directory(tmp_path,monkeypatch):
    from tiplog_py.figures.layout import source_identity
    expected = source_identity(); monkeypatch.chdir(tmp_path)
    assert source_identity() == expected
    assert expected['path'] == 'py/tiplog_py/figures/layout.py'


def test_topic_limits_use_utf8_bytes_and_segments():
    assert len(path_bytes('a'*4096)) == 4096
    assert path_bytes('/'.join(['a']*128))
    for invalid in ('a'*4097,'é'*2049,'/'.join(['a']*129)):
        with pytest.raises(TraceError,match='resource limit'): path_bytes(invalid)


@pytest.mark.parametrize('existing', [True,False])
def test_fetch_rejects_recorded_checksum_mismatch_without_replacing_manifest(tmp_path,monkeypatch,existing):
    from tiplog_py.data import fetch
    monkeypatch.chdir(tmp_path)
    filename = '12302019.NASDAQ_ITCH50.gz'
    dest = tmp_path/'raw'; dest.mkdir()
    data = b'new-authorized-fixture'
    path = dest/filename
    if existing: path.write_bytes(data)
    manifest = tmp_path/'manifest.json'
    saved = {'source_url':'https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/'+filename,
             'last_modified':'test-date','sha256':hashlib.sha256(b'original').hexdigest()}
    manifest.write_text(json.dumps(saved)+'\n'); before=manifest.read_bytes()
    commands=[]
    def run(argv,**kwargs):
        commands.append(argv)
        if '--head' in argv:
            Path(argv[argv.index('--output')+1]).write_text(f'Content-Length: {len(data)}\nLast-Modified: test-date\n')
        elif argv[0] == 'curl':
            Path(argv[argv.index('--output')+1]).write_bytes(data)
        return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(fetch.subprocess,'run',run)
    with pytest.raises(ValueError,match='SHA-256 differs'):
        fetch.main(['--source','nasdaq','--file',filename,'--dest',str(dest),'--manifest',str(manifest)])
    assert manifest.read_bytes()==before and path.read_bytes()==data
    assert any(argv[0]=='gzip' for argv in commands)


def test_fetch_same_recorded_checksum_is_reverified_with_mocked_tools(tmp_path,monkeypatch):
    from tiplog_py.data import fetch
    monkeypatch.chdir(tmp_path)
    filename='12302019.NASDAQ_ITCH50.gz'; dest=tmp_path/'raw'; dest.mkdir()
    data=b'unchanged-fixture'; (dest/filename).write_bytes(data)
    digest=hashlib.sha256(data).hexdigest()
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'source_url':'https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/'+filename,
                                   'last_modified':'test-date','sha256':digest}))
    def run(argv,**kwargs):
        if '--head' in argv:
            Path(argv[argv.index('--output')+1]).write_text(f'Content-Length: {len(data)}\nLast-Modified: test-date\n')
        return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(fetch.subprocess,'run',run)
    fetch.main(['--source','nasdaq','--file',filename,'--dest',str(dest),'--manifest',str(manifest)])
    assert json.loads(manifest.read_text())['sha256']==digest


@pytest.mark.parametrize('explicit',[False,True])
def test_custom_figure_output_keeps_analysis_beside_that_output(tmp_path,monkeypatch,explicit):
    from tiplog_py.figures import build as driver, tip
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(driver,'build',lambda *_args: {})
    observed={}
    def build_tip(rows,output,**kwargs):
        observed.update(kwargs)
        return {}
    monkeypatch.setattr(tip,'build',build_tip)
    destination=tmp_path/'redirected'/'figures'
    args=['--all','--output',str(destination),'--tip-rows','fixture.jsonl']
    expected=destination.parent/'derived/tip-summary.json'
    if explicit:
        expected=tmp_path/'explicit-summary.json'
        args+=['--summary-output',str(expected)]
    driver.main(args)
    assert observed['summary_path']==expected
    assert not (tmp_path/'results').exists()


def test_declared_evidence_workspace_controls_relative_sidecar_resolution(tmp_path,monkeypatch):
    from tiplog_py.analysis import summarize
    canonical=tmp_path/'canonical'; bundle=tmp_path/'copied-bundle'
    reference=Path('results/frequency-flags.json')
    for directory,flag in ((canonical,False),(bundle,True)):
        path=directory/reference; path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'samples':[{'block':'a','attempt':0,'flagged_over_10_percent':flag}]}))
    monkeypatch.setattr(summarize,'ROOT',canonical)
    source=bundle/'observations.jsonl'
    source.write_text(json.dumps(dict(status='ok',config_id='x',block='a',attempt=0,
                                     frequency_flags_reference=str(reference)))+'\n')
    assert summarize.read_rows(source,evidence_root=bundle)[0]['noise_flagged'] is True
    (bundle/reference).unlink()
    # A declared bundle must never borrow a similarly named canonical sidecar.
    output=bundle/'derived/summary.json'
    with pytest.raises(ValueError,match='missing frequency sidecar in declared evidence workspace'):
        summarize.build(source,output,evidence_root=bundle)
    assert not output.exists()


def test_journal_rejects_loss_before_its_saved_collection_boundary(tmp_path):
    rows,payload,marker=journal_fixture(tmp_path)
    payload['collection_offsets']['runs.jsonl']=50
    with pytest.raises(ValueError,match='committed prefix is shorter'):
        publish_commit(tmp_path,marker,payload,{'completed_processes':[]},{})


def test_independent_oracle_rejects_overlimit_subscription_before_matching():
    from tiplog_py.exp.oracle import matcher
    for path in ('a'*4097,'é'*2049,'/'.join(['a']*129)):
        with pytest.raises(ValueError,match='resource limit'):
            matcher('subtree:'+path)


def test_new_prepared_plans_and_t2_groups_declare_identity_version(tmp_path,monkeypatch):
    from tiplog_py.exp import run
    monkeypatch.setattr(run.matrix,'load',lambda _path: {})
    monkeypatch.setattr(run.matrix,'make_plan',lambda *_args,**_kwargs: [])
    monkeypatch.setattr(run,'build_accelerator',lambda: {})
    config=tmp_path/'config.toml'; config.write_text('# fixture')
    plan=run.prepare(config,tmp_path/'prepared',suite='training')
    assert plan['t2_group_identity_version']==2
    assert read_json(tmp_path/'prepared/plan.json')['t2_group_identity_version']==2
    assert aggregate_t2(t2_rows(20))[0]['t2_group_identity_version']==2


@pytest.mark.parametrize('offsets',[True,False])
@pytest.mark.parametrize('change',['wrong_identity','extra','reordered'])
def test_journal_rejects_valid_json_that_departs_from_pending_sequence(tmp_path,offsets,change):
    rows,payload,marker=journal_fixture(tmp_path)
    if not offsets: payload.pop('collection_offsets')
    unrelated=dict(rows[1],config_id='unrelated')
    invalid={'wrong_identity':[rows[0],unrelated],
             'extra':[rows[0],rows[1],unrelated],
             'reordered':[rows[1],rows[0]]}[change]
    path=tmp_path/'runs.jsonl'; before=b''.join(map(encoded,invalid)); path.write_bytes(before)
    with pytest.raises(ValueError,match='authoritative pending journal sequence'):
        publish_commit(tmp_path,marker,payload,{'completed_processes':[]},{})
    assert path.read_bytes()==before
    assert read_json(marker)['status']=='pending'


@pytest.mark.parametrize('offsets',[True,False])
def test_journal_keeps_old_committed_prefix_before_exact_pending_prefix(tmp_path,offsets):
    rows,payload,marker=journal_fixture(tmp_path)
    old=dict(rows[0],process_round_id='earlier-process')
    prefix=encoded(old)
    if offsets: payload['collection_offsets']['runs.jsonl']=len(prefix)
    else: payload.pop('collection_offsets')
    path=tmp_path/'runs.jsonl'; path.write_bytes(prefix+encoded(rows[0])+encoded(rows[1])[:12])
    publish_commit(tmp_path,marker,payload,{'completed_processes':[]},{})
    assert path.read_bytes()==prefix+b''.join(map(encoded,rows))


@pytest.mark.parametrize('source_via_symlink',[True,False])
def test_output_cannot_replace_a_symlink_directory_ancestor_of_source(tmp_path,source_via_symlink):
    from tiplog_py._outputs import OutputTransaction
    actual=tmp_path/'actual'; actual.mkdir()
    original=binary_source(actual/'source.bin')
    link=tmp_path/'source-link'; link.symlink_to(actual,target_is_directory=True)
    source=(link if source_via_symlink else actual)/'source.bin'
    with pytest.raises(ValueError,match='preserve the source'):
        with OutputTransaction(source,[link]): pass
    assert source.read_bytes()==original and link.is_dir() and link.is_symlink()


@pytest.mark.parametrize('reverse',[True,False])
def test_output_tree_ancestors_are_rejected_before_reservation(tmp_path,reverse):
    from tiplog_py._outputs import OutputTransaction
    source=tmp_path/'source.bin'; original=binary_source(source)
    paths=[tmp_path/'output',tmp_path/'output'/'child']
    if reverse: paths.reverse()
    with pytest.raises(ValueError,match='distinct'):
        with OutputTransaction(source,paths): pass
    assert source.read_bytes()==original and not (tmp_path/'output').exists()
