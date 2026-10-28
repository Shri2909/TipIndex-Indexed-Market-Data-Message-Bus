import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
checks = []
with tempfile.TemporaryDirectory(prefix='p7-cli-isolated-') as directory:
    directory = Path(directory)
    def execute(binary, args, fixture=None):
        if fixture is not None:
            source = directory / 'input.tsv'
            source.write_text(fixture)
            args = [args[0], str(source), *args[1:]]
        result = subprocess.run([str(ROOT / binary), *args], text=True, capture_output=True)
        assert result.returncode == 0, (binary, args, result.stderr, result.stdout)
        return [json.loads(line) for line in result.stdout.splitlines()]
    for preset in ['release', 'asan-ubsan']:
        binary = f'build/{preset}/tiplog_layout'
        case = 'CASE\tquoted"case\t2\nCOST\t1\t0\t0\nNODE\t-\t1\tr\nNODE\t0\t2\tr/a\nNODE\t1\t3\tr/a/b\nCLASS\tone\t1\nTERM\tE\tr\nTERM\tE\tr/a/b\nCLASS\ttwo\t1\nTERM\tE\tr/a\nEND\n'
        rows = execute(binary, ['--input', '--methods', 'enum,dp', '--full-curves'], case)
        assert len(rows) == 2
        for row in rows:
            assert row['id'] == 'quoted"case' and row['exact'] and row['complete_domain']
            assert row['curve'] == [None, '12', '9', '6']
            assert row['objective'] == '9' and row['stores'] == 2
            assert sum(row['read_bytes']) == 9 and sum(row['useful_bytes']) == 6
        checks.append(dict(preset=preset, check='quoted_id_full_curve_at_budget', status='passed'))
        rows = execute(binary, ['--global-curves', '--multipliers', '5', '--budgets', '2'],
            'CURVE\tp\t1\t3\t1\nPOINT\t1\t10\nPOINT\t2\t8\nPOINT\t3\t0\nEND\n')
        assert rows[0]['counts'] == [1] and rows[0]['certified'] and rows[0]['objective'] == '10'
        assert rows[1]['available'] and rows[1]['bound'] == '5' and rows[1]['scale'] == '1'
        checks.append(dict(preset=preset, check='unsupported_global_budget_bound', status='passed'))
        rows = execute(binary, ['--global-curves', '--multipliers', '1', '--budgets', '2'],
            'CURVE\tunknown\t1\t2\t0\nEND\n')
        assert rows[0]['status'] == 'no_feasible_incumbent' and not rows[0]['certified']
        assert rows[0]['objective'] is None and not rows[1]['available']
        checks.append(dict(preset=preset, check='unknown_incomplete_curve_withholds_certificate', status='passed'))
        rows = execute(binary, ['--global-curves', '--multipliers', '1/2', '--budgets', '3'],
            'CURVE\ta\t2\t2\t1\nPOINT\t1\t10\nPOINT\t2\t8\nEND\nCURVE\tb\t3\t1\t1\nPOINT\t1\t12\nEND\n')
        assert rows[0]['counts'] == [2, 1] and rows[0]['scale'] == '6'
        assert rows[0]['objective'] == '48' and rows[0]['penalized'] == '57'
        assert rows[1]['bound'] == '48' and rows[1]['scale'] == '6'
        checks.append(dict(preset=preset, check='mixed_global_scales', status='passed'))
    example = subprocess.run([str(ROOT / 'build/release/tiplog_layout_example')], capture_output=True, text=True)
    assert example.returncode == 0, example.stderr
    data = json.loads(example.stdout)
    assert data['status'] == 'passed' and data['threshold_min'] == 28648000 and data['threshold_max'] == 38647999
    by_method = {row['method']: row for row in data['rows']}
    assert by_method['base']['waste'] == 5517460497
    assert by_method['figure']['waste'] == by_method['km-max']['waste'] == 39881491
    assert by_method['enum']['waste'] == by_method['dp']['waste'] == by_method['km-min']['waste'] == 30029491
    assert by_method['enum']['counts'] == [3, 1]
    checks.append(dict(preset='release', check='computed_worked_example', status='passed'))
print(json.dumps(dict(status='passed', sanitizer_leaks='inherits run_check detect_leaks=1; run outside sandbox ptrace', checks=checks), indent=2))
