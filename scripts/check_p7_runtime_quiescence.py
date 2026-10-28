#!/usr/bin/env python3
"""Apply the predeclared host-quiescence rule to every controlled P7 runtime round."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def epoch(text):
    return datetime.fromisoformat(text).timestamp()


def accepted_process_audit(record):
    """Bind sampling evidence to the exact accepted attempt, never a glob match."""
    status_path = Path(record['status_record'])
    if sha(status_path) != record['record_sha256']:
        raise ValueError('accepted status record identity changed')
    accepted = load(status_path)
    if (accepted.get('status') != 'passed' or accepted.get('controls_validated') is not True or
            any(accepted.get(key) != record.get(key)
                for key in ('round', 'kind', 'launcher_pid', 'output', 'settle', 'cpu3_idle_ratio'))):
        raise ValueError('accepted status record does not match the campaign round')
    acceptance_path = status_path.parent / f"round-{record['round']:02}.accepted.json"
    if load(acceptance_path) != accepted:
        raise ValueError('accepted/status records disagree')
    name = accepted['process_audit']
    expected = accepted['artifact_identities'][name]
    path = Path(name)
    if sha(path) != expected:
        raise ValueError('accepted process-audit identity changed')
    return path


def foreign_cpu23_seconds(path, launcher, hz):
    """Foreign CPU time of processes sampled on CPU2/3 at two consecutive snapshots."""
    if isinstance(hz, bool) or not isinstance(hz, (int, float)) or not math.isfinite(hz) or hz <= 0:
        raise ValueError('clock ticks per second must be finite and positive')
    snapshots=[json.loads(line) for line in Path(path).read_text().splitlines()]
    if len(snapshots) < 2:
        raise ValueError('process audit requires at least two nonempty snapshots')
    previous_time = None
    for sample in snapshots:
        at = epoch(sample['at_utc'])
        if not math.isfinite(at) or (previous_time is not None and at <= previous_time):
            raise ValueError('process snapshots must be chronological')
        previous_time = at
        processes = sample['processes']
        if not isinstance(processes, list) or not processes:
            raise ValueError('process snapshot must contain observed processes')
        identities = set()
        for process in processes:
            for field in ('pid', 'ppid', 'cpu', 'user_ticks', 'system_ticks'):
                if type(process[field]) is not int or process[field] < 0:
                    raise ValueError('invalid process identity or CPU counter')
            if process['pid'] == 0 or process['pid'] in identities or not isinstance(process['comm'], str):
                raise ValueError('duplicate or invalid process identity')
            identities.add(process['pid'])
    total=0.0;largest={}
    for before,after in zip(snapshots,snapshots[1:]):
        a={p['pid']:p for p in before['processes']};b={p['pid']:p for p in after['processes']}
        campaign={launcher};changed=True
        while changed:
            changed=False
            for p in (*a.values(),*b.values()):
                if p['ppid'] in campaign and p['pid'] not in campaign:
                    campaign.add(p['pid']);changed=True
        for pid,q in b.items():
            p=a.get(pid)
            if p is not None and any(q[field] < p[field] for field in ('user_ticks', 'system_ticks')):
                # PID reuse cannot be distinguished by the historical format.
                # Its counter discontinuity cannot certify a quiet interval.
                raise ValueError('process CPU counters decreased between snapshots')
            if p is None or pid in campaign or p['cpu'] not in (2,3) or q['cpu'] not in (2,3):
                continue
            seconds=(q['user_ticks']+q['system_ticks']-p['user_ticks']-p['system_ticks'])/hz
            total+=seconds
            largest[q['comm']]=largest.get(q['comm'],0.0)+seconds
    return total,dict(sorted(largest.items(),key=lambda item:-item[1])[:5])


def audit_campaign(rule_path):
    rule=load(rule_path)
    campaign_path=Path(rule['campaign'])
    campaign=load(campaign_path)
    samples=[json.loads(line) for line in Path(rule['sampler_output']).read_text().splitlines()]
    times = [sample['epoch'] for sample in samples]
    if (any(isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) for at in times)
            or any(after <= before for before, after in zip(times, times[1:]))):
        raise ValueError('CPU sampler timestamps must be finite and chronological')
    hz=rule['clock_ticks_per_second']
    rounds=[];failures=[]
    for record in campaign['rounds']:
        settle=record['settle']
        start,finish=epoch(settle['started_utc']),epoch(settle['finished_utc'])
        inside=[s for s in samples if start<=s['epoch']<=finish]
        if len(inside)<2:
            cpu2_idle=None
        else:
            idle=inside[-1]['cpu2']['idle']-inside[0]['cpu2']['idle']
            total=inside[-1]['cpu2']['total']-inside[0]['cpu2']['total']
            cpu2_idle=idle/total if total>0 and 0<=idle<=total else None
        identity_valid = False
        try:
            audit = accepted_process_audit(record)
            identity_valid = True
            foreign,largest=foreign_cpu23_seconds(audit,record['launcher_pid'],hz)
        except (OSError, ValueError, KeyError, TypeError) as error:
            row = {'round': record['round'], 'kind': record['kind'], 'status': 'failed',
                   'checks': {'accepted_attempt_identity': identity_valid,
                              'sampling_evidence_valid': False}, 'error': str(error)}
            rounds.append(row)
            failures.append(row)
            continue
        cpu3_idle=record['cpu3_idle_ratio']
        checks={'accepted_attempt_identity': True,
                'sampling_evidence_valid': True,
                'cpu2_settle_idle':cpu2_idle is not None and cpu2_idle>=rule['thresholds']['cpu2_settle_idle_min'],
                'foreign_cpu23_seconds':foreign<=rule['thresholds']['foreign_cpu23_seconds_max'],
                'cpu3_idle_ratio':isinstance(cpu3_idle, (int, float)) and not isinstance(cpu3_idle, bool)
                    and math.isfinite(cpu3_idle) and 0<=cpu3_idle<=1
                    and cpu3_idle>=rule['thresholds']['cpu3_idle_ratio_min']}
        row={'round':record['round'],'kind':record['kind'],'cpu2_settle_idle':cpu2_idle,'cpu2_settle_samples':len(inside),
             'foreign_cpu23_seconds':foreign,'largest_foreign':largest,'cpu3_idle_ratio':cpu3_idle,
             'process_audit':str(audit),'process_audit_sha256':sha(audit),'checks':checks,
             'status':'passed' if all(checks.values()) else 'failed'}
        rounds.append(row)
        if row['status']!='passed':
            failures.append(row)
    complete=(campaign['status']=='passed' and len(rounds)==11 and
              {row['round'] for row in rounds} == set(range(11)))
    result={'schema':'tiplog-p7-runtime-quiescence-v1','status':'passed' if complete and not failures else 'failed',
            'rule':str(rule_path),'rule_sha256':sha(rule_path),'campaign':str(campaign_path),'campaign_sha256':sha(campaign_path),
            'sampler_output':rule['sampler_output'],'sampler_output_sha256':sha(rule['sampler_output']),
            'rounds':rounds,'failures':failures}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rule', type=Path, default=Path('results/p7/runtime-quiescence-rule.json'))
    parser.add_argument('--output', type=Path, default=Path('results/p7/runtime-quiescence.json'))
    args = parser.parse_args(argv)
    try:
        result = audit_campaign(args.rule)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'schema': 'tiplog-p7-runtime-quiescence-v1', 'status': 'failed',
                  'rounds': [], 'failures': [{'error': str(error)}]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    rounds, failures = result['rounds'], result['failures']
    print(json.dumps({'status':result['status'],'rounds':len(rounds),
                      'failed_rounds':[r.get('round') for r in failures]}))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
