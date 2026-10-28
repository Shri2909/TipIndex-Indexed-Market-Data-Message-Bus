#!/usr/bin/env python3
"""Functional request-order/zero-volume registry regression, not a campaign."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def fixture():
    dictionary = [(1, 'x/a/e0'), (2, 'x/b/e1')]
    # The benchmark declares a 32-byte minimum aligned DATA record, matching
    # real ITCH inputs. Keep this fixture inside that already-approved bound.
    records = [(1, b'A'*16), (2, b'BC'*8+b'D'), (1, b'DEF'*6), (2, b'xyz'*3)]
    data = bytearray(64)
    data[:8] = b'TPLTRC\0\1'
    struct.pack_into('<I', data, 8, 1)
    struct.pack_into('<Q', data, 16, len(records))
    for number, (topic, payload) in enumerate(records, 1):
        data += struct.pack('<IHHQ', topic, len(payload), 0, number) + payload
        data += bytes((-len(data)) % 8)
    offset = len(data)
    data += struct.pack('<I', len(dictionary))
    for topic, path in dictionary:
        data += struct.pack('<IH', topic, len(path)) + path.encode()
    struct.pack_into('<QQ', data, 24, offset, len(data)-offset)
    return bytes(data), dictionary, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.parent / args.output.stem
    directory.mkdir(parents=True, exist_ok=True)
    raw, dictionary, records = fixture()
    trace = directory / 'synthetic-fixture.mdt'
    trace.write_bytes(raw)
    requests = [
        ('all-scan', 'subtree:x', 'scan'),
        ('new-exact', 'exact:z/new/e0', 'indexed'),
        ('new-subtree', 'subtree:z/new', 'indexed'),
        ('bad-kind', 'exact:z/valid;bad:wrong', 'scan'),
        ('new-exact-later', 'exact:z/new/e1', 'auto'),
        ('new-earlier-root', 'subtree:a/new', 'indexed'),
        ('bad-path', 'exact:bad//path', 'scan'),
        ('existing', 'exact:x/a/e0', 'indexed'),
        ('new-exact-duplicate', 'exact:z/new/e0', 'scan'),
    ]
    # Independently reconstruct the documented registry prefix insertion order.
    paths = []
    def intern(path):
        parts = path.split('/')
        for width in range(1, len(parts)+1):
            prefix = '/'.join(parts[:width])
            if prefix not in paths:
                paths.append(prefix)
    for _, path in dictionary:
        intern(path)
    valid = []
    for terms in sorted({item[1] for item in requests}):
        parsed = [term.split(':', 1) for term in terms.split(';')]
        if any(len(term) != 2 or term[0] not in ('exact', 'subtree') or
               not term[1] or '' in term[1].split('/') for term in parsed):
            continue
        for _, path in parsed:
            intern(path)
        valid.append(terms)
    digest = hashlib.sha256()
    for number, path in enumerate(paths, 1):
        text = path.encode()
        digest.update(struct.pack('<QQ', number, len(text)) + text)
    identity = digest.hexdigest()
    expected_counts = dict(registry_topics=len(paths),
                           registry_partitions=sum(path.count('/') < 2 for path in paths),
                           subscription_observers=sum(terms.startswith('subtree:') for terms in valid))
    report = {'status': 'running', 'timing_campaign': False, 'checks': 0,
              'fixture_sha256': hashlib.sha256(raw).hexdigest(), 'expected_paths': paths,
              'expected_registry': expected_counts, 'expected_registry_identity_sha256': identity,
              'runs': []}
    aliases = {terms: hashlib.sha256(terms.encode()).hexdigest()
               for _, terms, _ in requests}
    dictionary_path = directory / 'terms.tsv'
    dictionary_path.write_text(''.join(f'{alias}\t{terms}\n'
                                       for terms, alias in sorted(aliases.items())))
    reference_rows = None
    for encoding, order, rows in [('plain', 'forward', requests),
                                  ('plain', 'reverse', list(reversed(requests))),
                                  ('alias', 'forward', requests),
                                  ('alias', 'reverse', list(reversed(requests)))]:
        label = encoding+'-'+order
        tsv = directory / (label+'.tsv')
        tsv.write_text('id\texperiment\tafter_seq\tterms\tmode\tkernel\tcache\tbatch\treaders\n' +
                       ''.join(f'{name}\tfunctional\t0\t{"@"+aliases[terms] if encoding == "alias" else terms}\t{mode}\tbinheap\trepeat-warm\t2\t1\n'
                               for name, terms, mode in rows))
        output = directory / (label+'.jsonl')
        # Avoid appending to a prior functional attempt when rerun explicitly.
        if output.exists():
            raise RuntimeError('use a fresh output path for this audit')
        command = [str(args.binary), '--trace', str(trace), '--requests', str(tsv),
                   '--output', str(output), '--ring-bytes', '2048', '--block-entries', '64', '--memory']
        if encoding == 'alias':
            command += ['--term-dictionary', str(dictionary_path)]
        process = subprocess.run(command, text=True, capture_output=True)
        assert process.returncode == 0, process.stderr
        actual = [json.loads(line) for line in output.read_text().splitlines()]
        prefill = next(row for row in actual if row['kind'] == 'prefill')
        assert prefill['registry_identity_sha256'] == identity
        assert prefill['subscription_compilation_errors'] == 2
        assert prefill['publications'] == 4
        report['checks'] += 3
        by_id = {row['id']: row for row in actual if row['kind'] == 'replay'}
        assert len(by_id) == len(requests)
        report['checks'] += 1
        for row in actual:
            for key, value in expected_counts.items():
                if key == 'subscription_observers' and row['kind'] == 'memory':
                    continue
                assert row[key] == value, (order, row.get('id'), key, row)
                report['checks'] += 1
        for name, terms, _ in requests:
            row = by_id[name]
            if name.startswith('bad-'):
                assert row['status'] == 'invalid_config'
                report['checks'] += 1
                continue
            expected = []
            kind, path = terms.split(':', 1)
            for number, (topic, payload) in enumerate(records, 1):
                actual_path = dict(dictionary)[topic]
                wanted = actual_path.split('/')
                root = path.split('/')
                if wanted == root or (kind == 'subtree' and wanted[:len(root)] == root):
                    expected.append((number, payload))
            assert row['status'] == 'ok'
            assert row['out_count'] == len(expected)
            assert row['seq_sha256'] == hashlib.sha256(b''.join(struct.pack('<Q', n) for n, _ in expected)).hexdigest()
            assert row['payload_sha256'] == hashlib.sha256(b''.join(p for _, p in expected)).hexdigest()
            report['checks'] += 4
        memory = next(row for row in actual if row['kind'] == 'memory')
        assert memory['recount_equal'] is True
        report['checks'] += 1
        # Compare complete semantic output; discard only explicitly timing and
        # CPU/frequency observation fields from this functional fixture.
        observed = {name: {k: v for k, v in row.items() if k not in
                          {'wall_ns', 'cpu_ns', 'user_ns', 'system_ns', 'cpu_start',
                           'cpu_end', 'freq_start_khz', 'freq_end_khz'}}
                    for name, row in by_id.items()}
        if reference_rows is None:
            reference_rows = observed
        else:
            assert observed == reference_rows
            report['checks'] += len(observed)
        report['runs'].append({'command': command, 'exit_code': process.returncode,
                               'output': str(output), 'prefill': prefill,
                               'replay_rows': by_id, 'memory': memory})
    report['negative_dictionary_runs'] = []
    terms = 'exact:x/a/e0'
    alias = hashlib.sha256(terms.encode()).hexdigest()
    for label, text, error in [
        ('duplicate', f'{alias}\t{terms}\n{alias}\t{terms}\n', 'duplicate term dictionary id'),
        ('missing-tab', 'malformed line\n', 'malformed term dictionary line'),
        ('bad-id', f'xyz\t{terms}\n', 'malformed term dictionary line'),
        ('bad-sha', f'{"0"*64}\t{terms}\n', 'does not match term string SHA256')]:
        path = directory / (label+'-terms.tsv')
        path.write_text(text)
        command = [str(args.binary), '--trace', str(trace), '--term-dictionary', str(path),
                   '--output', str(directory/(label+'-rejected.jsonl')), '--ring-bytes', '2048']
        process = subprocess.run(command, text=True, capture_output=True)
        assert process.returncode != 0 and error in process.stderr
        report['checks'] += 1
        report['negative_dictionary_runs'].append(dict(command=command,
                                                        exit_code=process.returncode,
                                                        stderr=process.stderr))
    tsv = directory/'unknown-alias.tsv'
    tsv.write_text('unknown\tfunctional\t0\t@'+('0'*64)+'\tscan\tbinheap\trepeat-warm\t2\t1\n'
                   'malformed\tfunctional\t0\t@bad\tscan\tbinheap\trepeat-warm\t2\t1\n')
    output = directory/'unknown-alias.jsonl'
    command = [str(args.binary), '--trace', str(trace), '--term-dictionary', str(dictionary_path),
               '--requests', str(tsv), '--output', str(output), '--ring-bytes', '2048']
    process = subprocess.run(command, text=True, capture_output=True)
    assert process.returncode == 0, process.stderr
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    actual = [row for row in rows if row['kind'] == 'replay']
    assert len(actual) == 2
    assert all(row['status'] == 'invalid_config' and 'term alias' in row['reason'] for row in actual)
    assert all(row['registry_topics'] == 5 and row['registry_partitions'] == 3 for row in rows)
    report['checks'] += 4
    report['unknown_alias_run'] = dict(command=command, exit_code=process.returncode,
                                      rows=rows)
    report['status'] = 'passed'
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'status': 'passed', 'checks': report['checks'],
                      'output': str(args.output), 'timing_campaign': False}))


if __name__ == '__main__':
    main()
