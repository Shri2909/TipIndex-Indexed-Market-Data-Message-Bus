#!/usr/bin/env python3
"""Audit all accepted P7 observations and retain the exact analysis inputs."""
import hashlib
import json
from pathlib import Path

from tiplog_py.layout.analyze import build


def main():
    campaign_path = Path('results/raw/P7/studies/campaign.json')
    campaign = json.loads(campaign_path.read_text())
    assert campaign['status'] == 'passed'
    paths = [Path(item['output']) for item in campaign['files']]
    for path, record in zip(paths, campaign['files'], strict=True):
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest() == record['output_sha256']
    metadata = Path('results/raw/P7/inputs/metadata.json')
    summary_path = Path('results/derived/layout-summary.json')
    csv_path = Path('results/raw/P7/layout-claim-metrics.csv')
    manifest = {'schema':'tiplog-p7-analysis-inputs-v1','inputs':[str(p) for p in paths],
                'metadata':str(metadata),'campaign':str(campaign_path),
                'summary':str(summary_path),'csv':str(csv_path),
                'global':'results/derived/layout-global.json','worked_example':'results/p7/worked-example.json'}
    manifest['runtime']='results/derived/layout-runtime.json'
    Path('results/p7/analysis-inputs.json').write_text(json.dumps(manifest,indent=2)+'\n')
    summary = build(paths,metadata,csv_path=csv_path)
    summary_path.parent.mkdir(parents=True,exist_ok=True)
    summary_path.write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'status':summary['status'],'cases':summary['observed_cases'],
                      'rows':summary['rows'],'failures':summary['failure_counts'],
                      'summary':str(summary_path)}))
    return 1 if summary['failure_counts'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
