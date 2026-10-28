"""Verify the terminal P5 gate, not elapsed wall time or partial logs."""
import datetime
import importlib.util
import json
from pathlib import Path

runner = Path('scripts/run_fuzz_gate.py')
spec = importlib.util.spec_from_file_location('fuzz_gate', runner)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
gate = Path('results/p5/F3-integrated-segmented-gate-20261018T160110.829382Z.json')
data = json.loads(gate.read_text())
assert data['status'] == 'passed'
assert data['monotonic_seconds'] >= 1800
assert 'active_attempt' not in data
module.verify_completed(data)
config = data['configuration']
assert module.sha256(config['binary']) == config['binary_sha256']
assert module.sha256(runner) == config['runner_sha256']
corpus = Path(config['corpus'])
module.verify_corpus(corpus, data['corpus_checkpoint'])
assert module.corpus_manifest(corpus) == data['corpus_checkpoint']
assert config['environment']['TIPLOG_FUZZ_MODE'] == 'all'
assert 'detect_leaks=1' in config['environment']['ASAN_OPTIONS']
assert 'halt_on_error=1' in config['environment']['UBSAN_OPTIONS']
assert '-max_len=65536' in config['fixed_flags']
assert '-len_control=0' in config['fixed_flags']
freeze = json.loads(Path('results/p5/fuzz-source-freeze.json').read_text())
for name, digest in freeze['files'].items():
    assert module.sha256(name) == digest, name
artifacts = list(Path('results/p5/fuzz-artifacts').glob('*'))
assert not artifacts, artifacts
passed = [attempt for attempt in data['attempts'] if attempt['status'] == 'passed']
result = {
    'status': 'passed',
    'verified_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'gate': str(gate), 'gate_sha256': module.sha256(gate),
    'verification_script_sha256': module.sha256(Path(__file__)),
    'checks': ['terminal status and >=1800 confirmed monotonic seconds',
               'all exit codes/log hashes/terminal stats and accumulated totals',
               'binary/runner identity and exact terminal corpus identity',
               'all38 frozen sources unchanged',
               'full length range and leak/UB checks preserved',
               'no crash artifact'],
    'monotonic_seconds': data['monotonic_seconds'],
    'executions': data['executed_units'], 'segments': len(passed),
    'peak_rss_MiB': max(a['final_stats']['peak_rss_mb'] for a in passed),
    'source_files': len(freeze['files']),
    'corpus_files': len(data['corpus_checkpoint']),
    'binary_sha256': config['binary_sha256'],
}
Path('results/p5/fuzz-gate-verified.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
