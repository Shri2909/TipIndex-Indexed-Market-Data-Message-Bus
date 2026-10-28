#!/usr/bin/env python3
"""Read-only resource-budget preflight over frozen P7 inputs; never runs solvers."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
manifest = json.loads((ROOT / 'results/p7/input-manifest.json').read_text())
rows = []
for batch in manifest['batches']:
    path = ROOT / batch['path']
    cases = 0
    positive = classes = terms = 0
    total_work = maximum_case_work = maximum_membership_bound = 0
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            row = line.rstrip(b'\r\n').split(b'\t')
            if row[0] == b'CASE':
                positive = classes = terms = 0
            elif row[0] == b'NODE':
                positive += int(row[2]) != 0
            elif row[0] == b'CLASS':
                classes += 1
            elif row[0] == b'TERM':
                terms += 1
            elif row[0] == b'END':
                cases += 1
                work = positive * (classes + terms)
                total_work += work
                maximum_case_work = max(maximum_case_work, work)
                maximum_membership_bound = max(maximum_membership_bound, positive * classes)
    assert cases == batch['cases'], batch['path']
    assert path.stat().st_size == batch['bytes'], batch['path']
    assert digest.hexdigest() == batch['sha256'], batch['path']
    rows.append({'path':batch['path'], 'bytes':batch['bytes'], 'cases':cases,
                 'sha256':digest.hexdigest(),
                 'aggregate_preparation_work_bound':total_work,
                 'maximum_case_preparation_work_bound':maximum_case_work,
                 'maximum_case_membership_upper_bound':maximum_membership_bound,
                 'matches_frozen_sha256':True})
curves = []
for path in sorted((ROOT / 'results/raw/P7/global').glob('*.curves.tsv')):
    count = entries = maximum_entries = 0
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            row = line.rstrip(b'\r\n').split(b'\t')
            if row[0] == b'CURVE':
                current = int(row[3]) + 1
                count += 1
                entries += current
                maximum_entries = max(maximum_entries,current)
    curves.append({'path':str(path.relative_to(ROOT)), 'bytes':path.stat().st_size,
                   'sha256':digest.hexdigest(),
                   'curves':count, 'aggregate_entries':entries,'maximum_curve_entries':maximum_entries})
report = {'schema':'tiplog-remediation-frozen-budget-preflight-v1',
          'scope':'Read-only counting and SHA256; no exact/heuristic solver invocation or timing measurement',
          'batches':rows,'global_curve_batches':curves,
          'maxima':{'batch_bytes':max(r['bytes'] for r in rows),
                    'aggregate_preparation_work_bound':max(r['aggregate_preparation_work_bound'] for r in rows),
                    'case_preparation_work_bound':max(r['maximum_case_preparation_work_bound'] for r in rows),
                    'case_membership_upper_bound':max(r['maximum_case_membership_upper_bound'] for r in rows),
                    'global_batch_bytes':max(r['bytes'] for r in curves),
                    'global_aggregate_entries':max(r['aggregate_entries'] for r in curves)}}
report['default_budget_checks'] = {}
header = (ROOT / 'tools/tiplog_layout/input_budget.hpp').read_text()
report['budget_source_header'] = 'tools/tiplog_layout/input_budget.hpp'
report['budget_source_header_sha256'] = hashlib.sha256(
    (ROOT / report['budget_source_header']).read_bytes()).hexdigest()
byte_limit = int(re.search(r'max_bytes\{(\d+)ULL << 20\}', header).group(1)) << 20
preparation = re.search(r'PreparationLimits preparation\{(\d+),\s*(\d+)\}', header)
work_limit, membership_limit = map(int, preparation.groups())
curve_limit = int(re.search(r'max_curve_entries\{(\d+)\}', header).group(1))
for label, byte_limit, work_limit in [('initial', 64 << 20, 100000000),
                                      ('current', byte_limit, work_limit)]:
    rejected = [row['path'] for row in rows
                if row['bytes'] > byte_limit
                or row['aggregate_preparation_work_bound'] > work_limit
                or row['maximum_case_membership_upper_bound'] > membership_limit]
    rejected_curves = [row['path'] for row in curves
                       if row['bytes'] > byte_limit or row['aggregate_entries'] > curve_limit]
    report['default_budget_checks'][label] = {
        'max_input_bytes': byte_limit, 'max_prepare_work': work_limit,
        'max_curve_entries': curve_limit, 'max_prepared_entries': membership_limit,
        'rejected_case_batches': rejected, 'rejected_curve_batches': rejected_curves,
        'all_frozen_batches_fit': not rejected and not rejected_curves}
output=ROOT / 'audit/remediation/tools/frozen-budget-preflight.json'
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'input_batches':len(rows),'global_curve_batches':len(curves),'maxima':report['maxima']},indent=2))

assert report['default_budget_checks']['current']['all_frozen_batches_fit']
