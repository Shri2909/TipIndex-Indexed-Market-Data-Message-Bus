#!/usr/bin/env python3
"""Deterministic layout correctness closeout; outputs only in audit/remediation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'audit/remediation/tools'

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def run(preset):
    binary=ROOT/'build'/preset/'tiplog_layout_cc5'
    output=OUT/('cc5-final-'+preset+'.json')
    command=[str(binary),'--instances','10000','--seed','20191230','--output',str(output)]
    environment=os.environ.copy()
    if preset=='asan-ubsan':
        environment.update(ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                           UBSAN_OPTIONS='print_stacktrace=1:halt_on_error=1')
    before=digest(binary)
    completed=subprocess.run(command,cwd=ROOT,env=environment,capture_output=True,timeout=1200)
    (OUT/('cc5-final-'+preset+'.stdout')).write_bytes(completed.stdout)
    (OUT/('cc5-final-'+preset+'.stderr')).write_bytes(completed.stderr)
    actual=json.loads(output.read_text()) if output.exists() else None
    expected=json.loads((ROOT/'results/p7/cc5-release.json').read_text())
    return {'preset':preset,'command':command,'exit_code':completed.returncode,
            'binary_sha256':before,'binary_unchanged_during_check':digest(binary)==before,
            'output':str(output.relative_to(ROOT)),
            'output_sha256':digest(output) if output.exists() else None,
            'stdout_matches_output':completed.stdout==output.read_bytes() if output.exists() else False,
            'matches_historical_cc5_json':actual==expected,
            'completed_instances':actual.get('completed_instances') if actual else None,
            'result_fnv1a64':actual.get('result_fnv1a64') if actual else None,
            'stderr_empty':not completed.stderr}

with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(run,['release','asan-ubsan']))
# The frozen worked-example artifact is an independent pre-remediation snapshot.
original=ROOT/'results/p7/worked-example.json'
example_results=[]
for preset in ['release','asan-ubsan']:
    binary=ROOT/'build'/preset/'tiplog_layout_example'
    command=[str(binary)]
    p=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=120)
    output=OUT/('worked-example-final-'+preset+'.json')
    output.write_bytes(p.stdout)
    (OUT/('worked-example-final-'+preset+'.stderr')).write_bytes(p.stderr)
    example_results.append({'preset':preset,'command':command,'binary_sha256':digest(binary),
                            'exit_code':p.returncode,'output':str(output.relative_to(ROOT)),
                            'output_sha256':digest(output),'snapshot':str(original.relative_to(ROOT)),
                            'snapshot_sha256':digest(original),
                            'byte_identical_to_snapshot':p.stdout==original.read_bytes(),
                            'json_identical_to_snapshot':json.loads(p.stdout)==json.loads(original.read_text()),
                            'stderr_empty':not p.stderr})
summary={'schema':'tiplog-remediation-layout-correctness-closeout-v1',
         'at_utc':datetime.now(timezone.utc).isoformat(),
         'scope':'Correctness only; no performance claims. Historical artifacts read only.',
         'cc5':results,'worked_example':example_results}
summary['status']='passed' if all(r['exit_code']==0 and r['matches_historical_cc5_json'] and r['binary_unchanged_during_check'] and r['stderr_empty'] for r in results) and all(r['exit_code']==0 and r['json_identical_to_snapshot'] and r['stderr_empty'] for r in example_results) else 'failed'
(OUT/'layout-closeout.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
assert summary['status']=='passed'
