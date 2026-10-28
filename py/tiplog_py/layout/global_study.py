"""Execute and independently audit the approved nonnegative multiplier sweep."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import time

from .analyze import read_case_groups


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def number(value):
    return {'exact': str(value), 'value': float(value)} if value is not None else None


def validate_observation_rows(observations, multipliers, budgets):
    expected = {('global_point', str(Fraction(lam)), None) for lam in multipliers}
    expected.update(('global_budget_bound', str(Fraction(lam)), budget)
                    for lam in multipliers for budget in budgets)
    actual = [(row.get('type'), str(Fraction(row.get('lambda', '0'))),
               row.get('budget') if row.get('type') == 'global_budget_bound' else None)
              for row in observations]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('every required multiplier/point/budget-bound row must occur exactly once')


def execute(command, output, commands):
    before = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True)
    record = {'argv': command, 'exit_code': result.returncode, 'seconds': time.monotonic()-before,
              'stdout': result.stdout, 'stderr': result.stderr, 'output': str(output)}
    commands.append(record)
    if result.returncode:
        raise RuntimeError(f'global CLI failed: {record}')
    record['sha256'] = sha(output)
    return [json.loads(line) for line in output.read_text().splitlines()]


def run(args):
    campaign = json.loads(args.campaign.read_text())
    protocol = json.loads(args.protocol.read_text())
    if campaign['status'] != 'passed':
        raise ValueError('a complete accepted study campaign is required')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {'schema': 'tiplog-layout-global-v1', 'status': 'running', 'strata': [],
               'commands': [], 'checks': 0, 'failures': [],
               'provenance': {str(p): sha(p) for p in (args.campaign, args.protocol, Path(__file__), args.binary)},
               'scope': 'Supported nonnegative-penalty points only. Uncertified curves provide feasible candidates, never lower bounds. No general global knapsack solver.'}

    def check(condition, message):
        summary['checks'] += 1
        if not condition:
            raise AssertionError(message)

    for item in campaign['files']:
        if item['kind'] != 'real':
            continue
        check(sha(item['output']) == item['output_sha256'], 'study output identity')
        label = Path(item['input']).stem
        curves, baseline_budget, total_bytes, active_weight = [], 0, 0, Fraction(0)
        coverage_bytes = coverage_weight = 0
        for case_id, rows in read_case_groups([item['output']]):
            check(len(rows) == 5, 'every case has five methods')
            by_method = {row['method']: row for row in rows}
            base = by_method['base']
            baseline_budget += base['budget']
            total_bytes += base['total_bytes']
            weight = Fraction(int(base['active_class_weight']), int(base['class_weight_scale']))
            active_weight += weight
            complete = [by_method[m] for m in ('dp', 'enum') if by_method[m]['exact'] and
                        by_method[m]['solver_status'] == 'solved' and by_method[m]['complete_domain']]
            scale = int(base['scale'])
            values = [None] * (base['positive_nodes'] + 1)
            if complete:
                selected = complete[0]
                check(len(selected['curve']) == len(values), 'full exact count domain')
                values = [None if x is None else Fraction(int(x), int(selected['scale'])) for x in selected['curve']]
                for other in complete[1:]:
                    check(values == [None if x is None else Fraction(int(x), int(other['scale'])) for x in other['curve']], 'complete solvers agree at every count')
                coverage_bytes += base['total_bytes']
                coverage_weight += weight
            else:
                for row in rows:
                    if row['status'] != 'feasible' or row['objective'] is None:
                        continue
                    k = row['stores']
                    cost = Fraction(int(row['objective']), int(row['scale']))
                    if values[k] is None or cost < values[k]:
                        values[k] = cost
            check(any(v is not None for v in values), 'at least a known feasible candidate per partition')
            # Each local prepared problem has a common exact scale. Explicitly
            # require integer numerators rather than rounding fractions.
            for value in values:
                check(value is None or (value * scale).denominator == 1, 'exact curve scale')
            curves.append({'id': case_id, 'scale': scale, 'values': values, 'complete': bool(complete)})
        check(len(curves) == item['cases'] == 8907, 'every real partition present')
        complete_count = sum(c['complete'] for c in curves)
        certified = complete_count == len(curves)
        curve_path = args.output_dir / f'{label}.curves.tsv'
        with curve_path.open('w') as stream:
            for curve in curves:
                stream.write(f"CURVE\t{curve['id']}\t{curve['scale']}\t{len(curve['values'])-1}\t{int(curve['complete'])}\n")
                for k, value in enumerate(curve['values']):
                    if value is not None:
                        stream.write(f"POINT\t{k}\t{int(value*curve['scale'])}\n")
                stream.write('END\n')
        minimum_budget = sum(any(v is not None for v in c['values'][1:]) for c in curves)
        budgets = {minimum_budget, baseline_budget, max(minimum_budget, baseline_budget-1),
                   (minimum_budget+baseline_budget)//2}
        multipliers = protocol['global']['lambda']
        output = args.output_dir / f'{label}.initial.jsonl'
        command = [str(args.binary), '--global-curves', str(curve_path), '--multipliers', ','.join(multipliers),
                   '--budgets', ','.join(map(str, sorted(budgets))), '--output', str(output)]
        initial = execute(command, output, summary['commands'])
        validate_observation_rows(initial, multipliers, budgets)
        check(True, 'initial sweep supplies every multiplier and requested bound')
        budgets.update(row['stores'] for row in initial if row['type'] == 'global_point' and row['stores'] is not None)
        output = args.output_dir / f'{label}.jsonl'
        command[command.index('--budgets')+1] = ','.join(map(str, sorted(budgets)))
        command[-1] = str(output)
        observations = execute(command, output, summary['commands'])
        validate_observation_rows(observations, multipliers, budgets)
        check(True, 'all required global observation identities')
        points, bounds, expected_by_lambda = [], [], {}
        for row in observations:
            lam = Fraction(row['lambda'])
            if lam not in expected_by_lambda:
                minima = [min((value + lam*k, k, value) for k, value in enumerate(curve['values']) if value is not None)
                          for curve in curves]
                expected_by_lambda[lam] = (minima, sum((x[0] for x in minima), Fraction(0)))
            minima, penalty_sum = expected_by_lambda[lam]
            if row['type'] == 'global_point':
                expected_counts = [x[1] for x in minima]
                objective = sum((x[2] for x in minima), Fraction(0))
                check(row['counts'] == expected_counts and row['stores'] == sum(expected_counts), 'actual-count penalty tie choice')
                check(Fraction(int(row['objective']), int(row['scale'])) == objective, 'global objective independent rational check')
                check(Fraction(int(row['penalized']), int(row['scale'])) == penalty_sum, 'global penalized objective')
                check(row['certified'] == certified, 'certificate requires every complete curve')
                points.append({'lambda': str(lam), 'stores': row['stores'], 'objective': number(objective),
                               'penalized': number(penalty_sum), 'certified': certified,
                               'status': row['status'], 'point_interpretation': 'own-at-most-budget optimum' if certified else 'evaluated feasible candidate; no global exactness'})
            else:
                check(row['available'] == certified, 'incomplete curves never supply a bound')
                value = penalty_sum-lam*row['budget'] if certified else None
                if certified:
                    check(Fraction(int(row['bound']), int(row['scale'])) == value, 'unsupported-budget lower bound')
                bounds.append({'lambda': str(lam), 'budget': row['budget'], 'available': certified, 'bound': number(value)})
        budget_rows = []
        for budget in sorted(budgets):
            feasible = [p for p in points if p['stores'] <= budget]
            best = min(feasible, key=lambda p: (Fraction(p['objective']['exact']), p['stores'])) if feasible else None
            available = [b for b in bounds if b['budget'] == budget and b['available']]
            lower = max((Fraction(b['bound']['exact']) for b in available), default=None)
            upper = Fraction(best['objective']['exact']) if best else None
            if upper is not None and lower is not None:
                check(lower <= upper, 'valid lower and upper bounds')
            budget_rows.append({'budget': budget, 'best_evaluated_feasible': best,
                                'lower_bound': number(lower),
                                'exact': upper is not None and lower is not None and upper == lower,
                                'status': 'no_evaluated_feasible_point' if best is None else 'exact_by_matching_bounds' if upper == lower else 'feasible_with_bound' if lower is not None else 'feasible_without_global_bound'})
        summary['strata'].append({'label': label, 'partitions': len(curves), 'complete_partitions': complete_count,
                                  'complete_partition_fraction': number(Fraction(complete_count,len(curves))),
                                  'complete_byte_fraction': number(Fraction(coverage_bytes,total_bytes)) if total_bytes else None,
                                  'complete_weight_fraction': number(Fraction(coverage_weight,active_weight)) if active_weight else None,
                                  'global_certified': certified, 'baseline_budget': baseline_budget,
                                  'curve_file': str(curve_path), 'curve_sha256': sha(curve_path),
                                  'output': str(output), 'output_sha256': sha(output), 'points': points, 'budgets': budget_rows})
        print(f'{label}: {complete_count}/{len(curves)} complete curves; global certified={certified}', flush=True)
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2)+'\n')
    check(len(summary['strata']) == 24, 'all hierarchy/workload/beta strata')
    summary['status'] = 'passed'
    args.summary.write_text(json.dumps(summary, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, default=Path('results/p7/protocol.json'))
    parser.add_argument('--binary', type=Path, default=Path('build/release/tiplog_layout'))
    parser.add_argument('--output-dir', type=Path, default=Path('results/raw/P7/global'))
    parser.add_argument('--summary', type=Path, default=Path('results/derived/layout-global.json'))
    args = parser.parse_args()
    run(args)


if __name__ == '__main__':
    main()
