#!/usr/bin/env python3
"""Read-only SHA256 verification of every original listed P6 measurement file."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'audit/remediation/tools'

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

baseline_path=ROOT/'results/p6/auditor-t5-compatibility/measurement-files-before.json'
p8_path=ROOT/'results/p8/artifact-manifest.json'
identities=json.loads((ROOT/'audit/remediation/historical-identities.json').read_text())
original=json.loads(baseline_path.read_text())
p8=json.loads(p8_path.read_text())
p8_identity=identities['results/p8/artifact-manifest.json']
record=next(row for row in p8['packaging_inventory']['included'] if row['path']==str(baseline_path.relative_to(ROOT)))
changed=[]
checked=total_bytes=0
paths=set()
for row in original['files']:
    assert row['path'] not in paths
    paths.add(row['path'])
    path=ROOT/row['path']
    if not path.is_file():
        changed.append({'path':row['path'],'reason':'missing'})
        continue
    size=path.stat().st_size
    actual=digest(path)
    checked+=1
    total_bytes+=size
    if size!=row['bytes'] or actual!=row['sha256']:
        changed.append({'path':row['path'],'expected_bytes':row['bytes'],'actual_bytes':size,
                        'expected_sha256':row['sha256'],'actual_sha256':actual})
result={'schema':'tiplog-remediation-frozen-p6-identity-check-v1',
        'at_utc':datetime.now(timezone.utc).isoformat(),
        'scope':'Read-only comparison with original pre-postprocessing P6 file hashes; no measurements rerun',
        'original_identity_manifest':str(baseline_path.relative_to(ROOT)),
        'identity_manifest_original_at_utc':original['at_utc'],
        'identity_manifest_current_sha256':digest(baseline_path),
        'identity_manifest_bytes_match_retained_p8_inventory':baseline_path.stat().st_size==record['bytes'],
        'provenance_limit':'P8 inventories the measurement manifest by path/size, not by SHA256. The current audit baseline covers source/documents/corpus and does not include these raw files; the original 2026-10-25 manifest supplies their saved SHA256 identities.',
        'retained_p8_manifest_sha256':p8_identity['sha256'],
        'current_p8_manifest_sha256':digest(p8_path),
        'p8_manifest_matches_remediation_start_identity':digest(p8_path)==p8_identity['sha256'] and p8_path.stat().st_size==p8_identity['bytes'],
        'original_files':len(original['files']),'files_verified':checked,
        'original_bytes':sum(row['bytes'] for row in original['files']),
        'current_bytes_verified':total_bytes,'changed_files':changed}
result['status']='passed' if len(original['files'])==checked==5364 and not changed and result['identity_manifest_bytes_match_retained_p8_inventory'] and result['p8_manifest_matches_remediation_start_identity'] else 'failed'
(OUT/'frozen-p6-measurements.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
assert result['status']=='passed'
