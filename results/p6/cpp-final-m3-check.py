#!/usr/bin/env python3
"""Functional M3 fixture audit; does not run benchmark timing campaigns.

The trace encoder, posting lists, lower_bound and integer RNG below are a
separate Python reference. It imports no production project modules.
"""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import struct
import subprocess

MASK = (1 << 64) - 1
BASIS = 14695981039346656037


def fold(state, value):
    return ((state ^ value) * 1099511628211) & MASK


class Random:
    def __init__(self):
        self.state = 20191230

    def next(self):
        self.state = (self.state + 0x9e3779b97f4a7c15) & MASK
        value = self.state
        value = ((value ^ (value >> 30)) * 0xbf58476d1ce4e5b9) & MASK
        value = ((value ^ (value >> 27)) * 0x94d049bb133111eb) & MASK
        return value ^ (value >> 31)

    def bounded(self, bound):
        threshold = ((1 << 64) - bound) % bound
        while True:
            value = self.next()
            if value >= threshold:
                return value % bound


def fixture():
    topics = [(1, 'x/a/e0'), (2, 'x/b/e1'), (3, 'x/a/e2'),
              (4, 'y/e'), (5, 'solo'), (6, 'x')]
    owners = [1, 2, 3, 4, 5, 6, 1, 1, 3, 2, 5, 4, 6, 3, 2, 1]
    sizes = [0, 1, 7, 8, 9, 31, 64, 2, 3, 24, 16, 63, 4, 5, 6, 17]
    records = list(zip(owners, sizes))
    data = bytearray(64)
    data[:8] = b'TPLTRC\0\1'
    struct.pack_into('<I', data, 8, 1)
    struct.pack_into('<Q', data, 16, len(records))
    for number, (topic, size) in enumerate(records, 1):
        data += struct.pack('<IHHQ', topic, size, 0, number)
        data += bytes((number + i) & 255 for i in range(size))
        data += bytes((-len(data)) % 8)
    dictionary_start = len(data)
    data += struct.pack('<I', len(topics))
    for topic, path in topics:
        text = path.encode()
        data += struct.pack('<IH', topic, len(text)) + text
    struct.pack_into('<QQ', data, 24, dictionary_start, len(data)-dictionary_start)
    return bytes(data), records


def expected(records):
    # The dictionary creates partitions x, x/a, x/b, y, y/e, solo, in this
    # order. This fixture pins internal-node and unused-ancestor handling.
    partition_for_topic = {1: 1, 2: 2, 3: 1, 4: 4, 5: 5, 6: 0}
    lists = [[] for _ in range(6)]
    position, input_hash = 0, BASIS
    for topic, size in records:
        partition = partition_for_topic[topic]
        lists[partition].append(position)
        input_hash = fold(fold(input_hash, partition), position)
        position += ((16 + size + 7) // 8) * 8
    scan_hash = BASIS
    for items in lists:
        for item in items:
            scan_hash = fold(scan_hash, item)
    active = [p for p, items in enumerate(lists) if items]
    random, query_hash, seek_hash = Random(), BASIS, BASIS
    for _ in range(4096):
        partition = active[random.bounded(len(active))]
        lower = (random.bounded(position // 8) + 1) * 8
        query_hash = fold(fold(query_hash, partition), lower)
        offset = bisect.bisect_left(lists[partition], lower)
        found = lists[partition][offset] if offset < len(lists[partition]) else MASK
        seek_hash = fold(seek_hash, found)
    return dict(input_hash_hex=f'{input_hash:x}', query_hash_hex=f'{query_hash:x}',
                seek_hash=f'{seek_hash:x}', scan_hash=f'{scan_hash:x}', logical_head=position)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.parent
    directory.mkdir(parents=True, exist_ok=True)
    raw, records = fixture()
    path = directory / 'independent-synthetic-fixture.mdt'
    path.write_bytes(raw)
    result = {'timing_campaign': False, 'fixture': str(path),
              'fixture_sha256': hashlib.sha256(raw).hexdigest(), 'checks': 0, 'runs': []}
    for limit in [None, 7]:
        command = [str(args.binary), '--verify-only', '--trace', str(path)]
        if limit is not None:
            command += ['--records', str(limit)]
        process = subprocess.run(command, text=True, capture_output=True)
        if process.returncode:
            raise RuntimeError(process.stderr)
        actual = json.loads(process.stdout)
        count = len(records) if limit is None else limit
        reference = expected(records[:count])
        assert actual['status'] == 'ok' and actual['records'] == count
        assert len(actual['inputs']) == 8
        for row in actual['inputs']:
            operation, block = row['profile'].split('/')
            assert int(block[1:]) == row['block_entries']
            assert row['block_entries'] in [64, 256, 1024, 4096]
            assert row['records'] == row['input_records'] == count
            assert row['diagnostic'] == (limit is not None)
            assert row['operations_per_iteration'] == (4096 if operation == 'M3-seek' else count)
            assert row['input_hash_hex'] == reference['input_hash_hex']
            assert row['query_hash_hex'] == reference['query_hash_hex']
            assert row['expected_hash_hex'] == reference['seek_hash' if operation == 'M3-seek' else 'scan_hash']
            assert row['logical_head'] == reference['logical_head']
            assert row['partition_slots'] == 6 and row['seek_queries'] == 4096
            assert row['trace_file_bytes'] == len(raw) and row['trace_path'] == str(path)
            assert row['hash_algorithm'] == 'word-xor-multiply64-v1'
            result['checks'] += 12
        result['runs'].append({'command': command, 'exit_code': process.returncode,
                               'reference': reference, 'actual': actual})
    command = [str(args.binary), '--verify-only', '--trace', str(path), '--records', '0']
    process = subprocess.run(command, text=True, capture_output=True)
    assert process.returncode != 0 and 'requires nonempty real trace' in process.stderr
    result['checks'] += 1
    result['empty_selection'] = dict(command=command, exit_code=process.returncode,
                                     stderr=process.stderr)
    result['status'] = 'passed'
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'checks': result['checks'],
                      'output': str(args.output), 'timing_campaign': False}))


if __name__ == '__main__':
    main()
