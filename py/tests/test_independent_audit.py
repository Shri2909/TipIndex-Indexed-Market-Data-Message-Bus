"""Regressions from the independent October 2026 parser/resource audit."""
import struct
import json

import numpy as np
import pytest

from tiplog_py.exp.oracle import TraceIndex
from tiplog_py.trace.format import HEADER, MAGIC, TraceReader, TraceWriter


def trace_bytes(*, count=0, records=b'', dictionary=struct.pack('<I', 0), offset=None):
    offset = HEADER.size + len(records) if offset is None else offset
    return HEADER.pack(MAGIC, 1, 0, count, offset, len(dictionary), 0, bytes(16)) + records + dictionary


@pytest.mark.parametrize('data', [
    b'', b'short',
    trace_bytes(count=10_000),
    trace_bytes(count=(1 << 64)-1),
    trace_bytes(offset=63),
    trace_bytes(dictionary=b''),
    trace_bytes(dictionary=struct.pack('<I', 100)),
    trace_bytes(dictionary=struct.pack('<IIH', 1, 1, 4097) + b'a'*4097),
    trace_bytes(dictionary=struct.pack('<I', 2) + struct.pack('<IH', 1, 1) + b'a'
                + struct.pack('<IH', 2, 1) + b'a'),
])
def test_independent_parser_rejects_invalid_metadata_before_cache_allocation(tmp_path, monkeypatch, data):
    path = tmp_path/'input.mdt'
    path.write_bytes(data)
    def forbidden(*args, **kwargs):
        pytest.fail('invalid metadata must reject before index allocation')
    monkeypatch.setattr(np.lib.format, 'open_memmap', forbidden)
    instance = TraceIndex.__new__(TraceIndex)
    with pytest.raises(ValueError):
        instance.__init__(path, tmp_path/'cache')
    assert instance.stream is instance.data is instance.rows is None
    assert not list((tmp_path/'cache').iterdir())


def test_independent_parser_failed_record_cleans_owned_cache_and_input(tmp_path):
    path = tmp_path/'input.mdt'
    dictionary = struct.pack('<IIH', 1, 1, 3) + b'a/b'
    path.write_bytes(trace_bytes(count=1, records=struct.pack('<IHHQ', 1, 65535, 0, 1),
                                dictionary=dictionary))
    cache = tmp_path/'cache'; cache.mkdir()
    unrelated = cache/'unrelated.partial.npy'; unrelated.write_bytes(b'preserve')
    instance = TraceIndex.__new__(TraceIndex)
    with pytest.raises(ValueError, match='record'):
        instance.__init__(path, cache)
    assert instance.stream is instance.data is instance.rows is None
    assert list(cache.iterdir()) == [unrelated]
    assert unrelated.read_bytes() == b'preserve'


def test_independent_parser_cache_publication_failure_cleans_owned_files(tmp_path, monkeypatch):
    path = tmp_path/'input.mdt'
    with TraceWriter(path, '00'*32) as writer:
        writer.append('a/b', b'x', 1)
    from pathlib import Path
    original = Path.replace
    def fail_publication(self, target):
        if self.name.endswith('.partial.npy'):
            raise OSError('injected cache publication failure')
        return original(self, target)
    monkeypatch.setattr(Path, 'replace', fail_publication)
    instance = TraceIndex.__new__(TraceIndex)
    with pytest.raises(OSError, match='injected'):
        instance.__init__(path, tmp_path/'cache')
    assert instance.stream is instance.data is instance.rows is None
    assert not list((tmp_path/'cache').iterdir())


@pytest.mark.parametrize('stage', ['write', 'close', 'replace'])
def test_trace_writer_finish_failure_aborts_owned_staging(tmp_path, monkeypatch, stage):
    path = tmp_path/'output.mdt'; path.write_bytes(b'old destination')
    writer = TraceWriter(path, '00'*32)
    writer.append('a/b', b'x', 1)
    underlying = writer.stream
    class FailedStream:
        failed = False
        def __getattr__(self, name):
            return getattr(underlying, name)
        def write(self, data):
            if stage == 'write':
                raise OSError('injected write failure')
            return underlying.write(data)
        def close(self):
            underlying.close()
            if stage == 'close' and not self.failed:
                self.failed = True
                raise OSError('injected close failure')
    writer.stream = FailedStream()
    if stage == 'replace':
        from pathlib import Path
        monkeypatch.setattr(Path, 'replace', lambda *args: (_ for _ in ()).throw(OSError('injected rename failure')))
    with pytest.raises(OSError, match='injected'):
        writer.__exit__(None, None, None)
    assert writer.closed and underlying.closed
    assert not writer.partial.exists()
    assert path.read_bytes() == b'old destination'


def test_trace_writer_and_independent_cache_success_remain_identical(tmp_path):
    path = tmp_path/'input.mdt'
    with TraceWriter(path, '00'*32) as writer:
        writer.append('a/b', b'x', 1)
    with TraceReader(path) as reader:
        assert [record.payload for record in reader] == [b'x']
    with TraceIndex(path, tmp_path/'cache') as first:
        expected = first.rows.copy()
        sha = first.trace_sha256
    with TraceIndex(path, tmp_path/'cache') as second:
        assert second.trace_sha256 == sha
        np.testing.assert_array_equal(second.rows, expected)
    second.close()  # Resource cleanup is safe after an earlier explicit close.


def normalized_rows(path):
    path.write_text(json.dumps(dict(exp='T1', config_id='failed', status='crash'))+'\n')
    return path.read_bytes()


@pytest.mark.parametrize('alias', ['direct', 'symlink', 'hardlink', 'table', 'summary_table'])
def test_analysis_rejects_entire_write_set_aliases_before_writing(tmp_path, alias):
    import os
    from tiplog_py.analysis.summarize import build
    source = tmp_path/'raw.jsonl'
    original = normalized_rows(source)
    output = tmp_path/'summary.json'
    if alias == 'direct': output = source
    elif alias == 'symlink': output.symlink_to(source)
    elif alias == 'hardlink': os.link(source, output)
    elif alias == 'table':
        source.rename(tmp_path/'tip-outcomes.csv')
        source = tmp_path/'tip-outcomes.csv'
    else: output = tmp_path/'tip-statistics.csv'
    with pytest.raises(ValueError, match='distinct'):
        build(source, output)
    assert source.read_bytes() == original
    assert not (tmp_path/'tip-paired-ratios.csv').exists()


def test_analysis_protects_used_frequency_sidecar(tmp_path):
    from tiplog_py.analysis.summarize import build
    sidecar = tmp_path/'frequency.json'
    sidecar.write_text(json.dumps(dict(samples=[])))
    source = tmp_path/'raw.jsonl'
    source.write_text(json.dumps(dict(exp='T1', config_id='failed', status='crash',
                                     frequency_flags_reference='frequency.json'))+'\n')
    original = sidecar.read_bytes()
    with pytest.raises(ValueError, match='distinct'):
        build(source, sidecar, evidence_root=tmp_path)
    assert sidecar.read_bytes() == original


@pytest.mark.parametrize('stage', ['table', 'publish'])
def test_analysis_failed_bundle_preserves_old_outputs(tmp_path, monkeypatch, stage):
    from tiplog_py.analysis import summarize
    import os
    source = tmp_path/'raw.jsonl'; original = normalized_rows(source)
    output = tmp_path/'summary.json'
    paths = [output, *(tmp_path/name for name in summarize.TABLE_NAMES)]
    for index, path in enumerate(paths): path.write_text(f'old-{index}')
    before = {path: path.read_bytes() for path in paths}
    if stage == 'table':
        def fail(*args, **kwargs): raise OSError('injected table failure')
        monkeypatch.setattr(summarize, 'write_tables', fail)
    else:
        replace = os.replace
        failed = False
        def fail(source, target):
            nonlocal failed
            if not failed and target == paths[-1]:
                failed = True
                raise OSError('injected publish failure')
            return replace(source, target)
        monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='injected'):
        summarize.build(source, output)
    assert source.read_bytes() == original
    assert {path: path.read_bytes() for path in paths} == before
    assert not list(tmp_path.glob('.*.partial'))


@pytest.mark.parametrize('target', ['input', 'metadata', 'global'])
def test_layout_analysis_protects_all_read_inputs(tmp_path, target):
    from tiplog_py.layout.analyze import build
    paths = {name: tmp_path/f'{name}.json' for name in ('input', 'metadata', 'global')}
    for name, path in paths.items(): path.write_text(json.dumps(dict(name=name)))
    before = {name: path.read_bytes() for name, path in paths.items()}
    with pytest.raises(ValueError, match='distinct'):
        build([paths['input']], paths['metadata'], csv_path=paths[target], global_paths=[paths['global']])
    assert {name: path.read_bytes() for name, path in paths.items()} == before


@pytest.mark.parametrize('target', ['summary_input', 'csv_input', 'same_outputs'])
def test_layout_cli_rejects_summary_and_csv_collisions(tmp_path, target):
    from tiplog_py.layout.analyze import main
    source = tmp_path/'input.jsonl'; source.write_text('original')
    metadata = tmp_path/'metadata.json'; metadata.write_text('{}')
    output = source if target == 'summary_input' else tmp_path/'summary.json'
    csv = source if target == 'csv_input' else output if target == 'same_outputs' else tmp_path/'rows.csv'
    with pytest.raises(ValueError, match='distinct'):
        main(['--input', str(source), '--metadata', str(metadata), '--output', str(output), '--csv', str(csv)])
    assert source.read_text() == 'original'
    assert metadata.read_text() == '{}'


@pytest.mark.parametrize('sizes', [np.array([-1]), np.array([0]), np.array([1.5]),
                                  np.array([[24]]), np.array([True])])
def test_retention_rejects_invalid_sizes_before_search(sizes, monkeypatch):
    from tiplog_py.exp.oracle import retained_layout
    def forbidden(*args, **kwargs): pytest.fail('invalid size reached PAD search')
    monkeypatch.setattr(np, 'searchsorted', forbidden)
    with pytest.raises(ValueError): retained_layout(sizes, 64)


@pytest.mark.parametrize('sizes,capacity', [
    ([1 << 63, 1 << 63], 1 << 63),
    ([(1 << 62)+8]*3, 1 << 63),
    ([24], 1 << 64),
])
def test_retention_rejects_unrepresentable_data_or_pad_positions(sizes, capacity):
    from tiplog_py.exp.oracle import retained_layout
    with pytest.raises(ValueError): retained_layout(np.array(sizes, dtype='u8'), capacity)


def test_retention_preserves_exact_uint64_search_boundaries():
    from tiplog_py.exp.oracle import retained_layout
    # A scalar whole-item queue uses Python integers throughout, independently
    # of NumPy prefix sums/search keys and the production PAD computation.
    for power in (52, 53, 54, 61, 62, 63):
        capacity = 1 << power
        for delta in (1, 2, 7, 8, 15, 16, 63):
            schedules = [[capacity//2, delta, capacity//2, delta],
                         [capacity//2+delta, capacity//2-delta, delta],
                         [capacity-2*delta, delta, 3*delta]]
            for sizes in schedules:
                items, head, seq, pad_bytes, positions = [], 0, 1, 0, []
                for size in sizes:
                    remaining = capacity-head%capacity
                    if size > remaining:
                        items.append((head, remaining, None)); head += remaining; pad_bytes += remaining
                    positions.append(head)
                    items.append((head, size, seq)); head += size; seq += 1
                    while items and head-items[0][0] > capacity: items.pop(0)
                data = [item for item in items if item[2] is not None]
                actual = retained_layout(np.array(sizes, dtype='u8'), capacity)
                assert [int(value) for value in actual['positions']] == positions
                assert actual['head_pos'] == head
                assert actual['tail_pos'] == (items[0][0] if items else head)
                assert actual['tail_seq'] == (data[0][2] if data else seq)
                assert actual['retained_data'] == len(data)
                assert actual['pad_bytes'] == pad_bytes
