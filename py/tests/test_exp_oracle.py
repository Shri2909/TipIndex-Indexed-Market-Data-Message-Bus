"""Meaningful independent oracle vectors, retention and experiment provenance."""
import hashlib
import json
from pathlib import Path
import random
import struct
import numpy as np
import pytest
from tiplog_py.exp.hashes import ByteAccelerator, FNV_OFFSET, build_accelerator, scalar_fnv
from tiplog_py.exp.oracle import TraceIndex, OutcomeOracle, retained_layout, matches, validate
from tiplog_py.exp.synthetic import SplitMix64, schedule
from tiplog_py.trace.format import TraceWriter


@pytest.fixture(scope='module')
def accelerator(tmp_path_factory):
    record = build_accelerator(tmp_path_factory.mktemp('independent-byte-accelerator'))
    assert record['returncode'] == 0
    return ByteAccelerator(Path(record['binary']))


def test_independent_byte_accelerator_crossvectors_and_chunking(accelerator):
    rng = random.Random(45)
    data, offsets, lengths, seqs = bytearray(), [], [], []
    scalar = FNV_OFFSET
    for index in range(150):
        payload = rng.randbytes(rng.randrange(0, 513))
        offsets.append(len(data)); lengths.append(len(payload)); seqs.append((1 << 63)+index)
        data.extend(payload)
        scalar = scalar_fnv(scalar, seqs[-1], payload)
    expected = hashlib.sha256(data).hexdigest()
    for chunk_size in (1, 7, 150):
        state, digest = FNV_OFFSET, hashlib.sha256()
        for start in range(0, 150, chunk_size):
            state = accelerator.update(data, offsets[start:start+chunk_size], lengths[start:start+chunk_size],
                                       seqs[start:start+chunk_size], state, digest)
        assert state == scalar
        assert digest.hexdigest() == expected
    with pytest.raises(ValueError, match='outside'):
        accelerator.update(data, [len(data)], [1], [1], FNV_OFFSET, hashlib.sha256())


def scalar_layout(sizes, capacity):
    items, head, seq, pads = [], 0, 1, 0
    positions = []
    for size in sizes:
        remain = capacity-head%capacity
        if size > remain:
            items.append((head, remain, None)); head += remain; pads += remain
        positions.append(head)
        items.append((head, size, seq)); head += size; seq += 1
        while items and head-items[0][0] > capacity: items.pop(0)
    data_items = [item for item in items if item[2] is not None]
    return positions, head, items[0][0] if items else head, data_items[0][2] if data_items else seq, pads


def test_prefix_layout_matches_independent_whole_item_queue():
    rng = random.Random(771)
    for capacity in (64, 128, 256, 1024):
        for _ in range(30):
            sizes = [rng.choice((16, 24, 32, 40, 48, 56)) for _ in range(rng.randrange(0, 200))]
            actual = retained_layout(np.array(sizes, dtype='u8'), capacity)
            expected = scalar_layout(sizes, capacity)
            assert list(actual['positions']) == expected[0]
            assert (actual['head_pos'], actual['tail_pos'], actual['tail_seq'], actual['pad_bytes']) == expected[1:]


def test_trace_oracle_success_zero_match_expiry_future(tmp_path, accelerator, monkeypatch):
    monkeypatch.setattr('tiplog_py.exp.oracle.ByteAccelerator', lambda: accelerator)
    trace = tmp_path/'independent.mdt'
    with TraceWriter(trace, '01'*32) as writer:
        writer.append('itch/A/add/anon', b'abc', 1)
        writer.append('itch/A/modify/delete', b'', 2)
        writer.append('itch/B/trade/print', b'xyz', 3)
        writer.append('itch/A/add/anon', b'abc', 4)
    with TraceIndex(trace, tmp_path/'cache') as source:
        oracle = OutcomeOracle(source, 128)
        for threshold in (-1,1,2,3,4,5,100,2,1,100):
            assert oracle.after_timestamp(threshold) == sum(row['ts'] < threshold for row in source.rows)
        expected = oracle.expected(0, 'subtree:itch/A/add;subtree:itch/A')
        assert expected['out_count'] == 3
        assert expected['seq_sha256'] == hashlib.sha256(struct.pack('<QQQ', 1, 2, 4)).hexdigest()
        assert expected['payload_sha256'] == hashlib.sha256(b'abcabc').hexdigest()
        sink = FNV_OFFSET
        for seq, payload in [(1,b'abc'), (2,b''), (4,b'abc')]: sink = scalar_fnv(sink, seq, payload)
        assert expected['sink64'] == sink
        assert expected['checkpoint'] == {'after_seq': 4, 'next_pos': 88}
        missing = oracle.expected(0, 'exact:itch/C/never')
        assert missing['out_count'] == 0 and missing['status'] == 'ok'
        future = oracle.expected(100, 'subtree:itch')
        assert future['checkpoint'] is None and future['status'] == 'ok'
        short = OutcomeOracle(source, 64)
        expired = short.expected(0, 'subtree:itch')
        assert expired['status'] == 'history_expired' and expired['checkpoint'] is None
        assert expired['error'] == {'kind':'history_expired','requested_after':0,'last_delivered':0,'oldest_retained':2}
        assert validate(expected, expected)['status'] == 'passed'
        assert validate(dict(expected, out_count=2), expected)['status'] == 'failed'
    # Reuse only exact trace/index hashes, never trust an unverified local cache.
    with TraceIndex(trace, tmp_path/'cache') as reused: assert len(reused.rows) == 4


def test_raw_path_matching_boundaries():
    assert matches('itch/A/add/x', 'subtree:itch/A/add')
    assert not matches('itch/AA/add/x', 'subtree:itch/A')
    assert not matches('itch/A/add/x', 'exact:itch/A/add')
    with pytest.raises(ValueError): matches('itch/A', 'wildcard:itch')


def test_splitmix_vectors_and_synthetic_determinism():
    rng = SplitMix64(0)
    assert [rng.next() for _ in range(3)] == [0xe220a8397b1dcdaf, 0x6e789e6aa1b965f4, 0x06c45d188009454f]
    options = dict(records=80, partitions=10, zipf=.8, run_length=16, seed=20191230, mix=[(12,3),(36,7)])
    first = schedule(**options); second = schedule(**options)
    assert first[0] == second[0] and np.array_equal(first[1], second[1]) and first[2] == second[2]
    assert len(first[1]) == 80 and len(first[2]) == 30
    assert first[0][:int(first[1][0]['length'])] == bytes((20191230+17+i*31)&255 for i in range(int(first[1][0]['length'])))
