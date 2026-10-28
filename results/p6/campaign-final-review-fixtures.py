"""Review fixtures only; no experiment or measurement process is executed."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_p6_campaigns as campaign
import run_p6_micro as micro


def save(path, value):
    path.write_text(json.dumps(value))


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix='tiplog-campaign-final-') as name:
        directory = Path(name)
        a, b, destination = (directory / part for part in ('a.jsonl', 'b.jsonl', 'combined.jsonl'))
        a.write_bytes(b'{"fixture":1}\n')
        b.write_bytes(b'{"fixture":2}\n')
        destination.write_bytes(b'{"interrupted":')
        result = campaign.consolidate([a, b], destination)
        expected = a.read_bytes() + b.read_bytes()
        assert destination.read_bytes() == expected
        assert result['sha256'] == hashlib.sha256(expected).hexdigest()
        assert len(list(directory.glob('combined.jsonl.interrupted-*'))) == 1
        before = destination.stat().st_mtime_ns
        assert campaign.consolidate([a, b], destination) == result
        assert destination.stat().st_mtime_ns == before
        checks += ['partial concatenation retained and replaced completely', 'accepted concatenation reused by exact ordered source digest']

        owned, latest = directory / 'owned.json', directory / 'latest.json'
        save(owned, {'output_directory': str(directory / 'accepted')})
        save(latest, {'started_utc': '2026-10-24T15:00:00+00:00', 'output_directory': str(directory / 'unrelated'),
                      'configuration': {'kind': 'M1', 'repetitions': 15}})
        assert campaign.saved_micro_session(None, 'M1', 15, owned, latest) == directory / 'accepted/session.json'
        owned.unlink()
        previous = {'started_utc': '2026-10-24T12:00:00+00:00', 'child_session': str(directory / 'bound/session.json')}
        assert campaign.saved_micro_session(previous, 'M1', 15, owned, latest) == directory / 'bound/session.json'
        del previous['child_session']
        assert campaign.saved_micro_session(previous, 'M1', 15, owned, latest) == directory / 'unrelated/session.json'
        save(latest, {'started_utc': '2026-10-24T11:00:00+00:00', 'configuration': {'kind': 'M1', 'repetitions': 15}})
        try:
            campaign.saved_micro_session(previous, 'M1', 15, owned, latest)
        except RuntimeError:
            pass
        else:
            raise AssertionError('unattributable interrupted stage was accepted')
        checks += ['owned session preferred over mutable latest pointer', 'bound interrupted child reused',
                   'narrow pre-binding interruption recovered', 'unattributable interruption rejected']

        state = {'run_id': 'fixture', 'provenance': {'git': {'sha': 'fixture'}}}
        block = {'kind': 'M1', 'label': 'fixture', 'seed': 1, 'cases': 1}
        # The production helper stores project-relative references. These paths
        # are identifiers only; no benchmark directory or raw output is created.
        failure = micro.failed_process_row(state, block, 1, ROOT / 'results/p6/fixture-unused', 15,
                                           'truncated JSON format fixture')
        assert failure['status'] == 'crash' and failure['oracle_validated'] is False
        rows = directory / 'failures.jsonl'
        micro.append_observations(rows, [failure, failure])
        micro.append_observations(rows, [failure])
        assert len(rows.read_text().splitlines()) == 1
        checks += ['explicit process failure retained once by append identity']
    print(json.dumps({'status': 'passed', 'scope': 'temporary artifact-format and recovery fixtures only; no measurements',
                      'checks': checks}, indent=2))


if __name__ == '__main__':
    main()
