"""Independent trace/synthetic outcome oracle for V27.

The parser, raw-path matcher and whole-record/PAD retention calculation do not
import the C++ engine or its reference oracle. A compact disk-backed NumPy index
bounds RAM for the 32.8M-record trace; no message-level cache is a deliverable.
"""
from __future__ import annotations
from dataclasses import dataclass
from bisect import bisect_left
import hashlib
import json
import mmap
import os
from pathlib import Path
import struct
import tempfile
from typing import Iterable
import numpy as np
from .hashes import ByteAccelerator, FNV_OFFSET, sha_file

INDEX_DTYPE = np.dtype([('offset', '<u8'), ('ts', '<u8'), ('topic', '<u4'),
                        ('length', '<u2'), ('size', '<u4')])
HEADER = struct.Struct('<8sIIQQQQ16s')
RECORD = struct.Struct('<IHHQ')
CHUNK = 65536


def matcher(terms: str):
    exact, subtree = set(), set()
    for term in terms.split(';'):
        kind, separator, prefix = term.partition(':')
        if not separator or kind not in ('exact', 'subtree') or not prefix:
            raise ValueError('term must be exact:path or subtree:path')
        if (len(prefix.encode('utf-8')) > 4096 or prefix.count('/')+1 > 128 or
                any(not part for part in prefix.split('/')) or '\0' in prefix):
            raise ValueError('term path exceeds resource limit or is malformed')
        (exact if kind == 'exact' else subtree).add(prefix)
    def accepts(path):
        if path in exact: return True
        parts = path.split('/')
        return any('/'.join(parts[:n]) in subtree for n in range(1, len(parts)+1))
    return accepts


def matches(path: str, terms: str) -> bool:
    return matcher(terms)(path)


def dictionary(data, offset: int) -> dict[int, str]:
    if offset < 64 or offset % 8 or offset + 4 > len(data):
        raise ValueError('invalid independent dictionary boundary')
    count, = struct.unpack_from('<I', data, offset)
    cursor = offset + 4
    if count > (len(data) - cursor) // 7:
        raise ValueError('impossible independent dictionary count')
    topics = {}
    paths = set()
    for _ in range(count):
        if cursor + 6 > len(data):
            raise ValueError('truncated independent dictionary entry')
        topic, length = struct.unpack_from('<IH', data, cursor)
        cursor += 6
        if not length or length > 4096 or cursor + length > len(data):
            raise ValueError('invalid independent dictionary path length')
        path = data[cursor:cursor+length].decode('utf-8')
        cursor += length
        if (not topic or topic in topics or not path or any(not x for x in path.split('/')) or
                path in paths or path.count('/')+1 > 128 or '\0' in path):
            raise ValueError('invalid independent dictionary')
        topics[topic] = path
        paths.add(path)
    if cursor != len(data):
        raise ValueError('independent dictionary trailing bytes')
    return topics


class TraceIndex:
    """Build only outside measurement blocks; cache hash is validated on reuse."""
    def __init__(self, path: str | Path, cache: Path, *, rebuild=False):
        self.path, self.cache = Path(path), Path(cache)
        self.stream = self.data = self.rows = None
        try:
            self._initialize(rebuild=rebuild)
        except BaseException:
            self.close()
            raise

    def _initialize(self, *, rebuild):
        self.cache.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('rb')
        if self.stream.seek(0, 2) < HEADER.size:
            raise ValueError('truncated independent trace header')
        self.stream.seek(0)
        self.data = mmap.mmap(self.stream.fileno(), 0, access=mmap.ACCESS_COPY)
        magic, version, flags, count, offset, length, prefix, reserved = HEADER.unpack_from(self.data)
        if magic != b'TPLTRC\0\1' or version != 1 or flags or any(reserved):
            raise ValueError('invalid independent trace header')
        if offset + length != len(self.data) or offset < 64 or offset % 8:
            raise ValueError('independent trace region boundary')
        if count > (offset - HEADER.size) // RECORD.size:
            raise ValueError('impossible independent trace record count')
        self.topics = dictionary(self.data, offset)
        self.trace_sha256 = sha_file(self.path)
        stem = self.trace_sha256
        self.array_path = self.cache / (stem + '.npy')
        self.metadata_path = self.cache / (stem + '.json')
        valid = False
        if self.metadata_path.exists() and self.array_path.exists() and not rebuild:
            meta = json.loads(self.metadata_path.read_text())
            valid = (meta.get('trace_sha256') == self.trace_sha256 and
                     meta.get('index_sha256') == sha_file(self.array_path) and
                     meta.get('parser_version') == 2)
        if not valid:
            fd, name = tempfile.mkstemp(prefix=f'.{stem}.', suffix='.partial.npy', dir=self.cache)
            os.close(fd)
            temporary = Path(name)
            rows = None
            try:
                rows = np.lib.format.open_memmap(temporary, mode='w+', dtype=INDEX_DTYPE,
                                                 shape=(count,))
                cursor, previous_ts = 64, 0
                for index in range(count):
                    if cursor + RECORD.size > offset:
                        raise ValueError(f'truncated independent trace record {index}')
                    topic, payload_length, record_flags, timestamp = RECORD.unpack_from(self.data, cursor)
                    begin = cursor + 16
                    end = (begin + payload_length + 7) & ~7
                    if (end > offset or record_flags or topic not in self.topics or
                        timestamp < previous_ts or any(self.data[begin+payload_length:end])):
                        raise ValueError(f'invalid independent trace record {index}')
                    rows[index] = (begin, timestamp, topic, payload_length, end-cursor)
                    cursor, previous_ts = end, timestamp
                if cursor != offset:
                    raise ValueError('independent trace record count mismatch')
                rows.flush()
                rows._mmap.close()
                rows = None
                temporary.replace(self.array_path)
            finally:
                if rows is not None:
                    rows._mmap.close()
                temporary.unlink(missing_ok=True)
            meta = {'parser_version': 2, 'trace_sha256': self.trace_sha256,
                    'records': count, 'index_sha256': sha_file(self.array_path),
                    'source': str(self.path), 'index': str(self.array_path),
                    'scope': 'ignored local message-level cache; never redistribute'}
            self.metadata_path.write_text(json.dumps(meta, indent=2) + '\n')
        self.rows = np.load(self.array_path, mmap_mode='r')
        if not isinstance(self.rows, np.memmap):
            if hasattr(self.rows, 'close'):
                self.rows.close()
            self.rows = None
            raise ValueError('independent index is not a memory-mapped array')
        if self.rows.dtype != INDEX_DTYPE or self.rows.ndim != 1 or len(self.rows) != count:
            raise ValueError('independent index dtype/count mismatch')

    def close(self):
        if self.rows is not None:
            self.rows._mmap.close()
            self.rows = None
        if self.data is not None:
            self.data.close()
            self.data = None
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def retained_layout(sizes: np.ndarray, capacity: int) -> dict:
    """Use prefix sums and explicit PAD insertions, independent of append/evict."""
    sizes = np.asarray(sizes)
    maximum_position = (1 << 64) - 1
    if (type(capacity) is not int or capacity < 8 or capacity > maximum_position or
            capacity & (capacity - 1) or sizes.ndim != 1 or
            not np.issubdtype(sizes.dtype, np.integer)):
        raise ValueError('invalid ring capacity or oversized DATA')
    if len(sizes):
        largest = int(sizes.max())
        if int(sizes.min()) <= 0 or largest > capacity:
            raise ValueError('DATA sizes must be positive and fit the ring capacity')
        # The usual trace sizes establish safety in O(1) after the extrema scan.
        # Only unusually large integers need an exact Python-width sum.
        if len(sizes) * largest > maximum_position and sum(map(int, sizes)) > maximum_position:
            raise ValueError('DATA logical positions exceed u64')
    sizes = np.asarray(sizes, dtype='<u8')
    ends = np.cumsum(sizes, dtype=np.uint64)
    starts = ends - sizes
    pads = []
    boundary = capacity
    accumulated_pad = 0
    cursor = 0
    while cursor < len(sizes):
        # First DATA whose unpadded end lies beyond this physical ring end.
        threshold = boundary - accumulated_pad
        if threshold >= int(ends[-1]):
            break
        crossing = int(np.searchsorted(ends, np.uint64(threshold), side='right'))
        if crossing >= len(sizes):
            break
        before = int(starts[crossing]) + accumulated_pad
        padding = boundary - before
        if padding:
            pads.append((crossing, before, padding))
            accumulated_pad += padding
            if int(ends[-1]) + accumulated_pad > maximum_position:
                raise ValueError('DATA/PAD logical positions exceed u64')
        boundary += capacity
        cursor = crossing
    # Each PAD contributes one delta; a single prefix sum applies all padding.
    padding_deltas = np.zeros(len(sizes), dtype=np.uint64)
    for index, _begin, padding in pads:
        padding_deltas[index] += np.uint64(padding)
    positions = starts + np.cumsum(padding_deltas, dtype=np.uint64)
    head = int(positions[-1]) + int(sizes[-1]) if len(sizes) else 0
    cutoff = max(0, head-capacity)
    oldest_index = int(np.searchsorted(positions, np.uint64(cutoff), side='left'))
    tail = int(positions[oldest_index]) if oldest_index < len(sizes) else head
    for _index, begin, _padding in pads:
        if cutoff <= begin < tail:
            tail = begin
    return {'positions': positions, 'head_pos': head, 'tail_pos': tail,
            'head_seq': len(sizes)+1, 'tail_seq': oldest_index+1,
            'retained_data': len(sizes)-oldest_index,
            'pad_bytes': sum(p[2] for p in pads), 'pad_items': len(pads)}


def selected_partitions(topics: dict[int, str], terms: str) -> tuple[int, bool]:
    partitions = set()
    wide = False
    for term in terms.split(';'):
        kind, _, prefix = term.partition(':')
        if kind == 'subtree' and len(prefix.split('/')) < 2:
            wide = True
    accept = matcher(terms)
    for path in topics.values():
        if accept(path):
            partitions.add('/'.join(path.split('/')[:2]))
    return len(partitions), wide


def empty_hash() -> str:
    return hashlib.sha256(b'').hexdigest()


def digest_selection(data, rows, indices: np.ndarray, accelerator=None) -> dict:
    accelerator = accelerator or ByteAccelerator()
    seq_hash, payload_hash, sink = hashlib.sha256(), hashlib.sha256(), FNV_OFFSET
    for begin in range(0, len(indices), CHUNK):
        selected = indices[begin:begin+CHUNK]
        seqs = np.asarray(selected+1, dtype='<u8')
        seq_hash.update(seqs.tobytes())
        sink = accelerator.update(data, rows['offset'][selected], rows['length'][selected],
                                  seqs, sink, payload_hash)
    return {'out_count': len(indices), 'seq_sha256': seq_hash.hexdigest(),
            'payload_sha256': payload_hash.hexdigest(), 'sink64': sink}


class OutcomeOracle:
    def __init__(self, source: TraceIndex, capacity: int, *, anchor_ts: int | None = None):
        self.source, self.capacity = source, capacity
        count = len(source.rows) if anchor_ts is None else bisect_left(source.rows['ts'], anchor_ts)
        self.rows = source.rows[:count]
        self.layout = retained_layout(self.rows['size'], capacity)
        self.cache = {}
        self.term_info = {}
        self.time_checkpoints = {}

    def after_timestamp(self, timestamp: int) -> int:
        # The complete matrix repeats each backlog across many subscriptions,
        # arms and caches. Resolve each threshold once, rather than repeatedly
        # searching a large strided mmap view for identical input.
        if timestamp not in self.time_checkpoints:
            self.time_checkpoints[timestamp] = bisect_left(self.rows['ts'], timestamp)
        return self.time_checkpoints[timestamp]

    def expected(self, after_seq: int, terms: str, *, mode='scan', readers=1) -> dict:
        if after_seq < 0 or after_seq >= 1 << 64 or readers < 1:
            raise ValueError('invalid oracle request representation')
        key = (after_seq, terms)
        if terms not in self.term_info:
            accept = matcher(terms)
            matching_ids = [topic for topic, path in self.source.topics.items() if accept(path)]
            partitions = len({'/'.join(self.source.topics[topic].split('/')[:2]) for topic in matching_ids})
            wide = any(term.startswith('subtree:') and len(term[8:].split('/')) < 2
                       for term in terms.split(';'))
            self.term_info[terms] = (matching_ids, partitions, wide)
        matching_ids, partitions, wide = self.term_info[terms]
        if key not in self.cache:
            upper_seq = len(self.rows)
            oldest = self.layout['tail_seq']
            base = {'upper_seq': upper_seq, 'upper_pos': self.layout['head_pos'],
                    'checkpoint': None, 'error': None, 'status': 'ok'}
            if after_seq < upper_seq and after_seq+1 < oldest:
                base.update(status='history_expired', error={
                    'kind': 'history_expired', 'requested_after': after_seq,
                    'last_delivered': after_seq, 'oldest_retained': oldest})
                selected = np.empty(0, dtype=np.int64)
            else:
                if after_seq <= upper_seq:
                    base['checkpoint'] = {'after_seq': upper_seq,
                                          'next_pos': self.layout['head_pos']}
                start = min(after_seq, upper_seq)
                mask = np.isin(self.rows['topic'][start:], matching_ids)
                selected = np.flatnonzero(mask) + start
            base.update(digest_selection(self.source.data, self.rows, selected))
            self.cache[key] = base
        base = dict(self.cache[key])
        if mode == 'indexed' and not wide and partitions > 65535:
            base.update(status='invalid_config', checkpoint=None, error=None,
                        out_count=0, seq_sha256=empty_hash(), payload_sha256=empty_hash(),
                        sink64=FNV_OFFSET)
        if readers != 1:
            # Combined hashes intentionally repeat the output stream for every reader.
            # This uncommon shortcut is only used for identical-reader diagnostics;
            # actual T2 contains individual W2 reader requests and readers=1.
            raise ValueError('oracle requires one explicit request per reader')
        return base


def validate(actual: dict, expected: dict) -> dict:
    if expected['status'] == 'invalid_config':
        passed = actual.get('status') == 'invalid_config' and bool(actual.get('reason'))
        return {'check': 'V27/CC-4', 'status': 'passed' if passed else 'failed',
                'differences': {} if passed else {'invalid_config': actual}}
    keys = ('status', 'out_count', 'seq_sha256', 'payload_sha256', 'sink64',
            'checkpoint', 'error', 'upper_seq', 'upper_pos')
    differences = {key: {'actual': actual.get(key), 'expected': expected.get(key)}
                   for key in keys if actual.get(key) != expected.get(key)}
    return {'check': 'V27/CC-4', 'status': 'passed' if not differences else 'failed',
            'differences': differences}
