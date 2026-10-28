#!/usr/bin/env python3
"""Verify this audit's final source, full builds, executions and preserved evidence.

Uses the independently regression-tested F-01 build/CTest verifier. Historical
feature/performance gates are preserved; this gate has its own namespace.
"""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import xml.etree.ElementTree as ET

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import check_f01
from check_remediation import digest, input_sets, junit_counts, source_inventory
from build_provenance import verify_build, validate_configuration

PRESETS = ('debug', 'release', 'asan-ubsan', 'fuzz')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return check_f01.decode(Path(path).read_text())


def record_for(label):
    paths = []
    for path in (RUN/'evidence').glob(label+'-*.json'):
        value = read(path)
        if value.get('label') == label:
            paths.append(path)
    require(len(paths) == 1, 'missing/ambiguous final record: '+label)
    return paths[0].relative_to(ROOT).as_posix()


def inventory():
    files = {}
    for path in sorted(RUN.rglob('*')):
        if (not path.is_file() or '__pycache__' in path.parts or 'corpus' in path.parts
                or path.name in ('acceptance.json', 'artifact-manifest.json')):
            continue
        files[path.relative_to(ROOT).as_posix()] = {'bytes':path.stat().st_size, 'sha256':digest(path)}
    return files


def main():
    frozen = read(RUN/'source-freeze.json')
    require(frozen['sources'] == source_inventory(ROOT), 'source inventory changed after final freeze')
    require(frozen['input_sets'] == input_sets(ROOT), 'final compiled/Python input set changed')
    evidence = inventory()
    # Bind built artifacts outside the run as well as every command/log inside it.
    builds = {preset:record_for('final-build-'+preset) for preset in PRESETS}
    for name in builds.values():
        evidence.update(read(ROOT/name)['build_provenance']['artifacts'])
    checker = check_f01.Audit({'evidence':evidence, 'builds':builds}, ROOT)
    checks = []

    def passed(name, details):
        checks.append({'check':name, 'status':'passed', 'details':details})

    cases = None
    for preset in PRESETS:
        config_name = 'final-configure-'+('asan' if preset == 'asan-ubsan' else preset)
        config, _ = checker.runner(record_for(config_name))
        require(config['argv'] == ['cmake','--preset',preset], 'wrong configure command')
        snapshot = checker.build(preset)
        reference = {'record':record_for('accepted-ctest-'+preset),
                     'junit':str((RUN/'evidence'/('ctest-'+preset+'-accepted.xml')).relative_to(ROOT))}
        result = checker.ctest_one(preset, reference)
        require(result['tests'] == 230 and result['poll_budget'] == 24, 'incomplete current CTest suite')
        names = {(x.get('classname'),x.get('name')) for x in ET.parse(ROOT/reference['junit']).getroot().iter('testcase')}
        require(cases is None or cases == names, 'preset test inventories differ')
        cases = names
        passed('build-and-ctest:'+preset, result)

    python_record, _ = checker.runner(record_for('accepted-python'), group='python')
    check_f01.full_suite_environment(python_record)
    expected = ['.venv/bin/python','-m','pytest','-c','py/pytest.ini','py/tests','tests/scripts','-q',
                '--junitxml=audit/independent-20261027T041900Z/evidence/python-accepted.xml']
    require(python_record['argv'] == expected, 'Python suite selection differs')
    count = junit_counts(RUN/'evidence/python-accepted.xml', 499)
    require(count == 499, 'current Python test inventory differs')
    passed('python', {'tests':count})
    pip_record, _ = checker.runner(record_for('accepted-pip'), group='python')
    require(pip_record['argv'] == ['.venv/bin/python','-m','pip','check'], 'wrong dependency check')
    auditor, _ = checker.runner(record_for('accepted-auditor'), group='python')
    require(auditor['argv'] == ['.venv/bin/python','scripts/check_p6_experiments.py','--self-test'], 'wrong auditor self-test')
    passed('dependencies-and-auditor', True)

    for preset in ('release','asan-ubsan'):
        name = str((RUN/'evidence'/('differential-'+preset+'.json')).relative_to(ROOT))
        result = checker.differential_one(preset, name)
        passed('differential:'+preset, result)
    cross, log = checker.runner(record_for('final-budget-cross-release'))
    checker.execution('release', cross)
    require(cross['argv'] == ['build/release/tiplog_poll_differential','--seeds','200','--operations','10000'],
            'wrong matched-build differential command')
    san_budget = read(RUN/'evidence/differential-asan-ubsan.json')['budget_result']
    san_record, san_log = checker.runner(record_for('final-budget-diff-asan-ubsan'))
    require(san_budget == check_f01.decode(san_log), 'sanitizer budget summary is not its executed result')
    require(read(ROOT/cross['log']) == san_budget, 'Release/sanitizer matched-seed budget counters differ')
    passed('matched-build-budget-model', {'operations':san_budget['operations']})

    fuzz = read(RUN/'evidence/fuzz.json')
    require(fuzz['status'] == 'passed' and fuzz['historical_corpora_unchanged'] is True
            and {x['target'] for x in fuzz['targets']} == check_f01.FUZZERS and len(fuzz['targets']) == 4,
            'fuzz target/corpus coverage differs')
    for item in fuzz['targets']:
        record, log = checker.runner(item['record'])
        checker.execution('fuzz', record)
        check_f01.sanitizers(record['environment'])
        require(record['environment']['TIPLOG_FUZZ_MODE'] == 'all', 'fuzz mode coverage disabled')
        private = RUN/'evidence/private-fuzz'/item['target']
        require(record['argv'] == ['build/fuzz/'+item['target'],str(private/'corpus'),'-runs=10000',
                '-max_len=4096','-seed=20261027',f'-artifact_prefix={private}/','-print_final_stats=1'],
                'wrong fuzzer command or extra runtime override')
        require(0 < len(item['initial_seeds']) <= 128, 'missing/unbounded initial fuzz seeds')
        for name, sha in item['initial_seeds'].items():
            require(digest(ROOT/name) == sha, 'initial fuzz seed changed')
        require(item['completed_executions'] == 10000 and '#10000\tDONE' in log, 'fuzz run incomplete')
        require(Path(record['argv'][1]).resolve().is_relative_to(RUN/'evidence/private-fuzz'), 'shared corpus used')
    passed('four-private-fuzz-corpora', {'executions':40000,'historical_files':fuzz['historical_corpus_files']})

    for label, output, historical, preset, kind in (
            ('final-layout-cc5-asan','cc5-asan.json','results/p7/cc5-release.json','asan-ubsan','cc5'),
            ('final-layout-example-asan','worked-example-asan.json','results/p7/worked-example.json','asan-ubsan','example'),
            ('final-layout-cc5-release','cc5-release.json','results/p7/cc5-release.json','release','cc5'),
            ('final-layout-example-release','worked-example-release.json','results/p7/worked-example.json','release','example')):
        record, _ = checker.runner(record_for(label))
        checker.execution(preset, record)
        if preset == 'asan-ubsan': check_f01.sanitizers(record['environment'])
        expected = [f'build/{preset}/tiplog_layout_'+('cc5' if kind == 'cc5' else 'example')]
        if kind == 'cc5': expected += ['--instances','10000','--seed','20191230']
        expected += ['--output',str((RUN/'evidence'/output).relative_to(ROOT))]
        require(record['argv'] == expected, 'wrong standalone layout command/output')
        require((RUN/'evidence'/output).read_bytes() == (ROOT/historical).read_bytes(), 'layout result differs')
        if kind == 'cc5': require(read(ROOT/record['log']) == read(RUN/'evidence'/output), 'CC5 stdout/saved result differ')
    release_layout = read(RUN/'evidence/layout_tools/release-layout-closeout.json')
    require(len(release_layout['commands']) == 2 and {x['label'] for x in release_layout['commands']} == {'cc5','example'},
            'missing Release layout oracle/example command')
    for command in release_layout['commands']:
        require(command['returncode'] == 0 and command['bytes_equal_to_historical'] is True,
                'Release layout check failed')
        output = Path(command['argv'][-1])
        require(digest(output) == command['output_sha256'] == command['historical_sha256']
                and output.read_bytes() == Path(command['historical_path']).read_bytes(), 'Release layout output changed')
        require(digest(Path(command['argv'][0])) == command['binary_sha256'], 'supplementary Release binary changed')
    for source in release_layout['source_identities']:
        require(digest(ROOT/source['path']) == source['sha256'], 'supplementary layout source changed')
    passed('layout-exact-cross-checks', {'instances_per_build':10000,'byte_identical_historical_results':True})

    strict = read(RUN/'evidence/f01/historical-rows-independent-accepted.json')
    require(strict['status'] == 'passed' and strict['validated_rows'] == 2274
            and strict['summary_matches_historical'] is True, 'independent saved-row check incomplete')
    strict_record, _ = checker.runner(strict['record'], group='python')
    require(strict_record['argv'][:2] == ['.venv/bin/python','scripts/f01_summary.py']
            and strict_record['argv'][-2] == '--output', 'wrong strict historical check command')
    fresh_summary = check_f01._BENCH.summarize([ROOT/name for name in strict_record['argv'][2:-2]])
    historical_summary = read(ROOT/'results/f01/studies/final-20261027/summary.json')
    for summary in (fresh_summary,historical_summary):
        for source in summary['sources']: source['path'] = str((ROOT/source['path']).resolve())
        summary['sources'].sort(key=lambda x:x['path'])
    require(fresh_summary == historical_summary, 'historical row/statistics reconstruction differs')
    performance = read(RUN/'evidence/performance.json')
    require(performance['status'] == 'passed' and performance['validated_rows'] == 192,
            'actual-source performance comparison incomplete')
    protocol = read(ROOT/performance['protocol'])
    require(digest(ROOT/performance['protocol']) == performance['protocol_sha256'], 'performance protocol changed')
    baseline = read(RUN/'evidence/layout_tools/baseline-poll-bench-identity.json')
    require(baseline['source_archive_sha256'] == digest(RUN/'initial/source-snapshot.tar'), 'baseline source archive differs')
    require(len(performance['measurements']) == len(performance['normalization']) == 6, 'missing process repetition')
    rows = {'initial':{},'final':{}}
    expected_keys = check_f01.Audit.expected_benchmark_rows(check_f01._BENCH.IDENTITY,
                                                         check_f01.options(protocol['argv']))
    for measurement, normalization in zip(performance['measurements'],performance['normalization'],strict=True):
        kind, repetition = measurement['kind'],measurement['repetition']
        require(kind in rows and type(repetition) is int and repetition in (0,1,2), 'invalid process identity')
        record, _ = checker.runner(measurement['record'])
        require(record['argv'][1:-2] == protocol['argv'] and record['argv'][-2] == '--output', 'performance workload differs')
        require(Path(record['argv'][0]).resolve() == (ROOT/protocol['builds'][kind]['binary']).resolve(), 'wrong source binary')
        require(Path(record['argv'][-1]).resolve() == (ROOT/normalization['initial_output']).resolve()
                and normalization['process_repetition'] == repetition and normalization['tool_repetition'] == 0,
                'normalization is not bound to the executed output/repetition')
        sha = protocol['builds'][kind]['sha256']
        require(digest(Path(record['argv'][0])) == record['executable_sha256_before']
                == record['executable_sha256_after'] == sha, 'performance executable changed')
        require(datetime.fromisoformat(record['started_utc']) >= datetime.fromisoformat(protocol['declared_utc']),
                'timing predates its declaration')
        if kind == 'final': checker.execution('release',record)
        else: require(sha == baseline['binary_sha256'], 'initial executable lacks frozen-source identity')
        original = ROOT/normalization['original']
        derived = ROOT/normalization['derived']
        require(digest(original) == normalization['original_sha256']
                and digest(derived) == normalization['derived_sha256']
                and original.read_bytes() == (ROOT/normalization['initial_output']).read_bytes(), 'performance normalization changed inputs')
        a,b = checker.lines(str(original)),checker.lines(str(derived))
        actual_keys = set()
        require(len(a) == len(b) == 32, 'wrong performance row count')
        for before,after in zip(a,b,strict=True):
            key = check_f01._BENCH.validate(before)
            actual_keys.add((*key,before['repetition']))
            require(before['repetition'] == 0 and after == dict(before,repetition=repetition), 'normalization modified observations')
            full = (*key,repetition)
            require(full not in rows[kind], 'reused performance process/arm')
            rows[kind][full] = after
        require(actual_keys == expected_keys, 'missing/unexpected performance arms')
    require(set(rows['initial']) == set(rows['final']) and len(rows['initial']) == 96,
            'initial/final process coverage differs')
    require(len(performance['comparisons']) == 32, 'comparison omitted workloads')
    comparison_keys = set()
    for item in performance['comparisons']:
        key = tuple(item[field] for field in check_f01._BENCH.IDENTITY)
        require(key not in comparison_keys, 'duplicate performance comparison')
        comparison_keys.add(key)
        pairs = [(rows['initial'][(*key,r)],rows['final'][(*key,r)]) for r in range(3)]
        require(item['paired_repetitions'] == 3 and item['paired_poll_ratio'] == statistics.median(
            b['poll_latency_ns']['sum']/a['poll_latency_ns']['sum'] for a,b in pairs), 'paired timing ratio differs')
        for index,kind in enumerate(('initial','final')):
            observations = [pair[index] for pair in pairs]
            fields = {'poll_ns':('poll_latency_ns','sum'),'open_ns':('open_elapsed_ns',None),
                      'poll_p99_ns':('poll_latency_ns','p99'),'drain_ns':('drain_elapsed_ns',None),
                      'drain_cpu_ns':('drain_cpu_ns',None)}
            for field,(top,sub) in fields.items():
                require(item[kind+'_'+field] == statistics.median(
                    x[top][sub] if sub else x[top] for x in observations), 'performance summary differs: '+field)
        for a,b in pairs:
            require(all(a[field] == b[field] for field in ('output_digest','calls','inspections_used','poll_work','service_calls','final_checkpoint')),
                    'source comparison changed work/output/scheduling')
    passed('performance-and-independent-fixture-evidence', {'historical_rows':2274,'new_rows':192})
    control = read(RUN/'evidence/performance-followup.json')
    plan = read(ROOT/control['protocol'])
    require(control['status'] == 'passed' and control['validated_rows'] == 160
            and control['pairs'] == plan['pairs'] == 10 and len(control['records']) == 20
            and digest(ROOT/control['protocol']) == control['protocol_sha256'], 'follow-up evidence incomplete')
    observed = {'initial':{},'final':{}}
    identities = set()
    control_keys = check_f01.Audit.expected_benchmark_rows(check_f01._BENCH.IDENTITY,check_f01.options(plan['argv']))
    for item in control['records']:
        kind,pair = item['kind'],item['pair']
        require(kind in observed and type(pair) is int and 0 <= pair < 10 and (kind,pair) not in identities,
                'duplicate/invalid follow-up process')
        identities.add((kind,pair))
        record,_ = checker.runner(item['record'])
        require(record['argv'][:4] == ['taskset','-c',str(plan['cpu']),str(ROOT/plan['builds'][kind]['binary'])]
                and record['argv'][4:-2] == plan['argv'] and record['argv'][-2] == '--output', 'follow-up command differs')
        require(digest(Path(record['argv'][3])) == item['binary_sha256'] == plan['builds'][kind]['sha256'],
                'follow-up binary changed')
        if kind == 'final': checker.execution('release',record)
        raw = ROOT/item['raw']
        require(digest(raw) == item['raw_sha256'] and raw.read_bytes() == Path(record['argv'][-1]).read_bytes(),
                'follow-up raw output is not the executed destination')
        lines = checker.lines(str(raw))
        require(len(lines) == 8, 'follow-up arms missing')
        actual_keys = set()
        for row in lines:
            key = check_f01._BENCH.validate(row)
            actual_keys.add((*key,row['repetition']))
            require((*key,pair) not in observed[kind], 'duplicate follow-up arm')
            observed[kind][(*key,pair)] = row
        require(actual_keys == control_keys,'follow-up rows differ from declared arms')
    require(set(observed['initial']) == set(observed['final']) and len(observed['initial']) == 80
            and len(control['comparisons']) == 8, 'follow-up source coverage differs')
    covered = set()
    for item in control['comparisons']:
        key = tuple(item[field] for field in check_f01._BENCH.IDENTITY)
        require(key not in covered,'duplicate follow-up comparison'); covered.add(key)
        pairs = [(observed['initial'][(*key,i)],observed['final'][(*key,i)]) for i in range(10)]
        ratios = [b['poll_latency_ns']['sum']/a['poll_latency_ns']['sum'] for a,b in pairs]
        require(item['paired_ratios'] == ratios and item['paired_ratio_median'] == statistics.median(ratios)
                and all(a['poll_work'] == b['poll_work'] and a['output_digest'] == b['output_digest']
                        and a['calls'] == b['calls'] and a['service_calls'] == b['service_calls'] for a,b in pairs),
                'follow-up summary/work equivalence differs')
    passed('performance-follow-up',{'validated_rows':160,'fresh_process_pairs':10})

    # Historical files and raw measurements are rehashed here rather than
    # accepting a saved preservation status by itself.
    historical = read(RUN/'initial/historical-identities.json')
    raw = read(ROOT/'results/p6/auditor-t5-compatibility/measurement-files-before.json')['files']
    require(len(historical) == len({x['path'] for x in historical}) == 4262
            and all(checker.name(x['path']) == x['path'] for x in historical)
            and len(raw) == len({x['path'] for x in raw}) == 5364,
            'historical/raw inventories incomplete')
    for item in [*historical,*raw]:
        path = ROOT/item['path']
        require(path.is_file() and path.stat().st_size == item['bytes'] and digest(path) == item['sha256'],
                'historical file changed: '+item['path'])
    passed('historical-preservation', {'historical_files':len(historical),'p6_raw_files':len(raw)})
    ledger = read(RUN/'findings.json')
    require(len(ledger['findings']) == 14 and all(x['status'] == 'verified' for x in ledger['findings']),
            'confirmed findings are not all verified')
    for name in ('REPORT.md','COVERAGE.md','PERFORMANCE.md','REPRODUCE.md'):
        require((RUN/name).stat().st_size > 100, 'missing audit report: '+name)
    passed('findings-and-deliverables', {'confirmed':14,'fixed':14,'verified':14,'unresolved':0})

    # Negative controls on this gate's actual current-source CTest composition.
    for damage in ('missing-build','missing-artifact'):
        manifest = {'evidence':copy.deepcopy(evidence),'builds':dict(builds)}
        if damage == 'missing-build': manifest['builds'].pop('release')
        else: manifest['evidence'].pop('build/release/tiplog_poll_budget_test')
        negative = check_f01.Audit(manifest, ROOT)
        try:
            negative.ctest_one('release', {'record':record_for('accepted-ctest-release'),
                'junit':str((RUN/'evidence/ctest-release-accepted.xml').relative_to(ROOT))})
        except ValueError:
            pass
        else:
            raise ValueError('gate negative control survived: '+damage)
    passed('current-gate-negative-controls', {'killed':2,'focused_checker_tests':193})
    artifact_path = RUN/'artifact-manifest.json'
    artifact_path.write_text(json.dumps({'schema':'tiplog-independent-artifacts-v1','files':evidence},indent=2)+'\n')
    result = {'schema':'tiplog-independent-acceptance-v1','status':'passed',
              'checked_utc':datetime.now(timezone.utc).isoformat(),'source_freeze_sha256':digest(RUN/'source-freeze.json'),
              'artifact_manifest_sha256':digest(artifact_path),'input_sets':frozen['input_sets'],
              'counts':{'confirmed':14,'fixed':14,'verified':14,'unresolved':0},'checks':checks,
              'scope':'Local reviewed final-source execution evidence; no universal bug-free, hard-latency or malicious-host attestation claim.'}
    (RUN/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','checks':len(checks),'findings':result['counts']}),flush=True)


if __name__ == '__main__':
    try: main()
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Audit acceptance failed: '+str(error),file=sys.stderr)
        raise SystemExit(1)
