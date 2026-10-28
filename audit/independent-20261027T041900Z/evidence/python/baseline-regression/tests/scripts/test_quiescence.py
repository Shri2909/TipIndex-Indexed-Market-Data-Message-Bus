"""Accepted-attempt binding must survive retained retries and artifact damage."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('quiescence', ROOT / 'scripts/check_p7_runtime_quiescence.py')
quiescence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quiescence)


def save(path, value):
    path.write_text(json.dumps(value))


def attempt(tmp_path):
    chosen = tmp_path / 'round-00-selected.process-audit.jsonl'
    chosen.write_text('selected process evidence\n')
    # Retained retries may have any lexical or filesystem iteration order.
    for name in ('000-old', 'zzz-old'):
        (tmp_path / f'round-00-{name}.process-audit.jsonl').write_text('other evidence\n')
    status = tmp_path / 'round-00-selected.status.json'
    accepted = dict(round=0, kind='warmup', status='passed', controls_validated=True,
                    launcher_pid=100, output=str(tmp_path/'round-00-selected.jsonl'),
                    settle={'started_utc': '2026-10-26T00:00:00+00:00',
                            'finished_utc': '2026-10-26T00:01:00+00:00'}, cpu3_idle_ratio=.99,
                    process_audit=str(chosen), artifact_identities={str(chosen): quiescence.sha(chosen)})
    save(status, accepted)
    save(tmp_path/'round-00.accepted.json', accepted)
    compact = {key: accepted[key] for key in ('round', 'kind', 'launcher_pid', 'output', 'settle', 'cpu3_idle_ratio')}
    compact.update(status_record=str(status), record_sha256=quiescence.sha(status))
    return compact, status, chosen


def test_explicit_accepted_attempt_wins_over_all_retry_names(tmp_path):
    compact, _, chosen = attempt(tmp_path)
    assert quiescence.accepted_process_audit(compact) == chosen


@pytest.mark.parametrize('damage', ['status', 'log', 'missing_log', 'acceptance', 'round', 'settle', 'cpu3'])
def test_changed_or_unbound_accepted_evidence_fails(tmp_path, damage):
    compact, status, chosen = attempt(tmp_path)
    if damage == 'status':
        status.write_text('{}')
    elif damage == 'log':
        chosen.write_text('modified')
    elif damage == 'missing_log':
        chosen.unlink()
    elif damage == 'acceptance':
        save(tmp_path/'round-00.accepted.json', {})
    elif damage == 'round':
        compact['round'] = 1
    elif damage == 'settle':
        compact['settle'] = dict(compact['settle'], finished_utc='2026-10-26T00:02:00+00:00')
    else:
        compact['cpu3_idle_ratio'] = 1.0
    with pytest.raises((ValueError, OSError)):
        quiescence.accepted_process_audit(compact)


def test_cli_failure_is_explicit_and_nonzero(tmp_path):
    destination = tmp_path/'result.json'
    assert quiescence.main(['--rule', str(tmp_path/'missing.json'), '--output', str(destination)]) == 1
    assert json.loads(destination.read_text())['status'] == 'failed'


def test_noise_is_read_from_accepted_log(tmp_path):
    compact, status, chosen = attempt(tmp_path)
    def sample(ticks):
        return {'at_utc': f'2026-10-26T00:00:{ticks//1000:02}+00:00',
                'processes': [dict(pid=77, ppid=1, cpu=2, user_ticks=ticks,
                                   system_ticks=0, comm='other-worker')]}
    chosen.write_text(json.dumps(sample(0))+'\n'+json.dumps(sample(1000))+'\n')
    document = json.loads(status.read_text())
    document['artifact_identities'][str(chosen)] = quiescence.sha(chosen)
    save(status, document)
    save(tmp_path/'round-00.accepted.json', document)
    compact['record_sha256'] = quiescence.sha(status)
    selected = quiescence.accepted_process_audit(compact)
    assert quiescence.foreign_cpu23_seconds(selected, compact['launcher_pid'], 100)[0] == 10


def campaign(tmp_path, damage=None):
    """Self-consistent artifact hashes must not hide missing/invalid sampling."""
    from datetime import datetime
    rounds = []
    for number in range(11):
        directory = tmp_path/f'{number:02}'; directory.mkdir()
        record, status, chosen = attempt(directory)
        accepted = json.loads(status.read_text())
        accepted.update(round=number, kind='warmup' if number == 0 else 'measured')
        process = dict(pid=77, ppid=1, cpu=2, user_ticks=0, system_ticks=0, comm='foreign')
        samples = [dict(at_utc='2026-10-26T00:00:00+00:00', processes=[process]),
                   dict(at_utc='2026-10-26T00:01:00+00:00', processes=[dict(process, user_ticks=10)])]
        if number == 0:
            if damage == 'empty': samples = []
            elif damage == 'singleton': samples = samples[:1]
            elif damage == 'empty_processes': samples[1]['processes'] = []
            elif damage == 'decreased_ticks': samples[0]['processes'][0]['user_ticks'] = 1000
            elif damage == 'duplicate_pid': samples[1]['processes'].append(dict(process))
            elif damage == 'reversed_time': samples.reverse()
            elif damage == 'noisy': samples[1]['processes'][0]['user_ticks'] = 1000
            elif damage == 'impossible_idle': accepted['cpu3_idle_ratio'] = 2.0
        chosen.write_text(''.join(json.dumps(sample)+'\n' for sample in samples))
        accepted['artifact_identities'][str(chosen)] = quiescence.sha(chosen)
        save(status, accepted)
        save(directory/f'round-{number:02}.accepted.json', accepted)
        record.update({key: accepted[key] for key in ('round', 'kind', 'cpu3_idle_ratio')})
        record['record_sha256'] = quiescence.sha(status)
        rounds.append(record)
    manifest = tmp_path/'campaign.json'; save(manifest, dict(status='passed', rounds=rounds))
    at = datetime.fromisoformat('2026-10-26T00:00:00+00:00').timestamp()
    cpu_samples = tmp_path/'cpu.jsonl'
    cpu_samples.write_text(json.dumps(dict(epoch=at, cpu2=dict(idle=0, total=0)))+'\n'
                           +json.dumps(dict(epoch=at+60, cpu2=dict(idle=95, total=100)))+'\n')
    rule = tmp_path/'rule.json'
    save(rule, dict(campaign=str(manifest), sampler_output=str(cpu_samples), clock_ticks_per_second=100,
                    thresholds=dict(cpu2_settle_idle_min=.9, foreign_cpu23_seconds_max=3,
                                    cpu3_idle_ratio_min=.9)))
    return rule


def test_complete_quiet_campaign_passes(tmp_path):
    result = quiescence.audit_campaign(campaign(tmp_path))
    assert result['status'] == 'passed'
    assert len(result['rounds']) == 11 and not result['failures']


@pytest.mark.parametrize('damage', ['empty', 'singleton', 'empty_processes', 'decreased_ticks',
                                   'duplicate_pid', 'reversed_time', 'noisy', 'impossible_idle'])
def test_hash_bound_missing_or_invalid_sampling_rejects_entire_campaign(tmp_path, damage):
    result = quiescence.audit_campaign(campaign(tmp_path, damage))
    assert result['status'] == 'failed'
    assert len(result['rounds']) == 11
    assert [row['round'] for row in result['failures']] == [0]
