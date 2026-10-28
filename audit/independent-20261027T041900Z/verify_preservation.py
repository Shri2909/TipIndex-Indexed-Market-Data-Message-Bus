#!/usr/bin/env python3
"""Read-only rehash of historical results and the authoritative P6 raw inventory."""
import hashlib
import json
from pathlib import Path
import subprocess

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    rows = json.loads((RUN/'initial/historical-identities.json').read_text())
    raw_inventory = ROOT/'results/p6/auditor-t5-compatibility/measurement-files-before.json'
    before = next(x for x in rows if x['path'] == str(raw_inventory.relative_to(ROOT)))
    assert sha(raw_inventory) == before['sha256']
    raw = json.loads(raw_inventory.read_text())['files']
    assert len(raw) == len({x['path'] for x in raw}) == 5364
    assert all(x['path'].startswith('results/raw/P6/') for x in raw)
    failed = []
    for item in [*rows, *raw]:
        path = ROOT/item['path']
        if not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            failed.append(item['path'])
    head = subprocess.check_output(['scripts/git.sh', 'rev-parse', 'HEAD'], cwd=ROOT).decode()
    assert head == (RUN/'initial/head.txt').read_text()
    result = {'status':'failed' if failed else 'passed', 'historical_files':len(rows),
              'historical_bytes':sum(x['bytes'] for x in rows), 'p6_raw_files':len(raw),
              'p6_raw_bytes':sum(x['bytes'] for x in raw), 'changed_files':failed,
              'head_unchanged':True, 'historical_inventory_sha256':sha(RUN/'initial/historical-identities.json'),
              'p6_original_inventory_sha256':sha(raw_inventory)}
    (RUN/'evidence/preservation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return bool(failed)


if __name__ == '__main__': raise SystemExit(main())
