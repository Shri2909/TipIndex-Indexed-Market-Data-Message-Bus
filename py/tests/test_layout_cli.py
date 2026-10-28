"""End-to-end optimizer file contracts and certificate refusal boundaries."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / 'build/release/tiplog_layout'


def invoke(tmp_path, text, *args, global_input=False):
    source = tmp_path / 'input.tsv'
    output = tmp_path / 'output.jsonl'
    source.write_text(text)
    command = [str(BINARY), '--global-curves' if global_input else '--input', str(source),
               '--output', str(output), *args]
    result = subprocess.run(command, capture_output=True, text=True)
    return result, [json.loads(line) for line in output.read_text().splitlines()] if output.exists() else []


def test_layout_cli_full_curve_has_separate_comparison_budget(tmp_path):
    text = ('CASE\tchain\t2\nCOST\t1\t0\t0\n'
            'NODE\t-\t1\tr\nNODE\t0\t2\tr/a\nNODE\t1\t3\tr/a/b\n'
            'CLASS\tone\t1\nTERM\tE\tr\nTERM\tE\tr/a/b\n'
            'CLASS\ttwo\t1\nTERM\tE\tr/a\nEND\n')
    result, rows = invoke(tmp_path, text, '--methods', 'enum,dp', '--full-curves')
    assert result.returncode == 0, result.stderr
    assert len(rows) == 2
    for row in rows:
        assert row['exact'] and row['complete_domain']
        assert row['budget'] == 2 and row['stores'] == 2
        assert row['curve'] == [None, '12', '9', '6']
        assert row['objective'] == '9'
    assert rows[0]['read_bytes'] == rows[1]['read_bytes']


def test_layout_cli_invalid_input_and_caps_remain_explicit(tmp_path):
    result, rows = invoke(tmp_path, 'CASE\tx\t1\nCOST\t1/0\t0\t0\nEND\n')
    assert result.returncode != 0
    assert rows[-1]['status'] == 'error'
    text = ('CASE\tx\t1\nCOST\t1\t0\t0\nNODE\t-\t1\tr\n'
            'NODE\t0\t2\tr/a\nCLASS\tone\t1\nTERM\tS\tr\nEND\n')
    result, rows = invoke(tmp_path, text, '--methods', 'base,enum,dp', '--max-work', '0')
    assert result.returncode == 0
    assert rows[0]['status'] == 'infeasible_budget'
    for row in rows[1:]:
        assert row['solver_status'] == 'state_limit'
        assert row['objective'] is None and not row['exact'] and not row['complete_domain']


def test_layout_cli_global_unsupported_and_incomplete_curves(tmp_path):
    text = 'CURVE\tp\t1\t3\t1\nPOINT\t1\t10\nPOINT\t2\t8\nPOINT\t3\t0\nEND\n'
    result, rows = invoke(tmp_path, text, '--multipliers', '5', '--budgets', '2', global_input=True)
    assert result.returncode == 0, result.stderr
    assert rows[0]['certified'] and rows[0]['stores'] == 1
    bound = rows[1]
    assert bound['status'] == 'certified_lower_bound'
    assert bound['bound'] == '5'
    result, rows = invoke(tmp_path, text.replace('\t3\t1\n', '\t3\t0\n'),
                          '--multipliers', '5', '--budgets', '2', global_input=True)
    assert result.returncode == 0
    assert not rows[0]['certified'] and rows[1]['status'] == 'unavailable'
    result, _ = invoke(tmp_path, text, '--multipliers', '-1', global_input=True)
    assert result.returncode != 0
