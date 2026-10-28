#!/usr/bin/env python3
"""Verify that adding P7 figures preserves the accepted P1/P6 results."""
import hashlib
import json
from pathlib import Path
import re


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    checks=[]
    def check(name,passed,detail=None):
        checks.append({'check':name,'status':'passed' if passed else 'failed','detail':detail})
    baseline=json.loads(Path('results/p7/p6-figure-extension-baseline.json').read_text())
    for name,expected in baseline.items():
        if name in ('py/tiplog_py/figures/build.py','results/figures/p6-figures.json'):
            continue
        check('P6 numerical/source byte identity:'+name,digest(Path(name).read_bytes())==expected['sha256'])
    figures=json.loads(Path('results/p7/figure-regeneration-baseline.json').read_text())
    for name,expected in figures['files'].items():
        raw=Path(name).read_bytes()
        normalized=re.sub(rb'/CreationDate\s*\(D:[^)]*\)',b'/CreationDate (NORMALIZED)',raw) if name.endswith('.pdf') else raw
        check('P1/P6 rendered content identity:'+name,digest(normalized)==expected['normalized_sha256'],
              {'current_sha256':digest(raw),'old_sha256':expected['sha256'],
               'normalization':'PDF CreationDate only' if name.endswith('.pdf') else 'none'})
    old=json.loads(Path('results/p7/baseline-p6-figures.json').read_text())
    new=json.loads(Path('results/figures/p6-figures.json').read_text())
    check('P6 manifest semantic fields unchanged',{k:v for k,v in old.items() if k!='artifacts'}=={k:v for k,v in new.items() if k!='artifacts'})
    check('P6 manifest artifact names unchanged',old['artifacts'].keys()==new['artifacts'].keys())
    for name,expected in new['artifacts'].items():
        check('P6 regenerated manifest actual artifact:'+name,digest(Path(name).read_bytes())==expected)
    result={'schema':'tiplog-p7-figure-compatibility-v1','status':'passed' if all(c['status']=='passed' for c in checks) else 'failed',
            'checks':checks,'failures':[c for c in checks if c['status']!='passed'],
            'scope':'P6 numerical/source byte identities, P1/P6 PNG bytes, PDF content except CreationDate, current manifest artifacts. Additive builder AST equivalence checked by core closeout.'}
    Path('results/p7/figure-extension-compatibility.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'checks':len(checks),'failures':result['failures']}))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
