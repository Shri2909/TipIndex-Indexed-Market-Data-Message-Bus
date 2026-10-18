"""V05/RC-2: portable bytes, corruption checks and independent C++ decoding."""

import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

from tiplog_py.trace import TraceError, TraceReader, TraceWriter


def make_trace(path):
    with TraceWriter(path, "0123456789abcdef" * 4) as writer:
        writer.append("itch/AAPL/add/anon", b"A\x00\x01", 34200000000000)
        writer.append("itch/AAPL/modify/executed", b"E", 34200000000001)
        writer.append("itch/AAPL/add/anon", b"", 34200000000002)
    return path.read_bytes()


def test_v05_header_golden_and_python_round_trip(tmp_path):
    path = tmp_path / "golden.tpl"
    data = make_trace(path)
    assert data[:16] == b"TPLTRC\0\1\x01\0\0\0\0\0\0\0"
    assert struct.unpack_from("<Q", data, 16) == (3,)
    assert data[40:48] == bytes.fromhex("0123456789abcdef")
    assert data[48:64] == bytes(16)
    assert data[64:80] == struct.pack("<IHHQ", 1, 3, 0, 34200000000000)
    assert data[80:88] == b"A\0\1\0\0\0\0\0"
    with TraceReader(path) as reader:
        records = list(reader)
        assert reader.record_count == 3
        assert reader.dictionary == {1: "itch/AAPL/add/anon", 2: "itch/AAPL/modify/executed"}
        assert [(record.topic_id, record.payload, record.ts_ns) for record in records] == [
            (1, b"A\0\1", 34200000000000), (2, b"E", 34200000000001), (1, b"", 34200000000002)]


def test_rc2_writer_is_byte_identical(tmp_path):
    first = make_trace(tmp_path / "first.tpl")
    second = make_trace(tmp_path / "second.tpl")
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_v05_all_truncated_prefixes_rejected(tmp_path):
    data = make_trace(tmp_path / "valid.tpl")
    for length in range(len(data)):
        with pytest.raises(TraceError):
            TraceReader(data[:length])


@pytest.mark.parametrize("offset,replacement", [
    (0, b"x"), (8, b"\x02"), (12, b"\x01"), (48, b"\x01"),
    (16, struct.pack("<Q", 2**64 - 1)), (24, struct.pack("<Q", 63)),
    (32, struct.pack("<Q", 2**64 - 1)), (64, struct.pack("<I", 99)),
    (70, b"\x01"), (83, b"\x01"),
])
def test_v05_malformed_header_records_flags_padding(tmp_path, offset, replacement):
    data = bytearray(make_trace(tmp_path / "valid.tpl"))
    data[offset:offset + len(replacement)] = replacement
    with pytest.raises(TraceError):
        TraceReader(data)


def test_v05_rejects_duplicate_ids_paths_and_noncanonical_utf8(tmp_path):
    valid = make_trace(tmp_path / "valid.tpl")
    dictionary = struct.unpack_from("<Q", valid, 24)[0]
    first_length = struct.unpack_from("<H", valid, dictionary + 8)[0]
    second_id_offset = dictionary + 10 + first_length
    for change_offset, replacement in [(dictionary + 4, struct.pack("<I", 0)),
                                       (second_id_offset, struct.pack("<I", 1)),
                                       (dictionary + 10, b"/"),
                                       (dictionary + 10, b"\xff"),
                                       (dictionary + 10, b"\0")]:
        data = bytearray(valid)
        data[change_offset:change_offset + len(replacement)] = replacement
        with pytest.raises(TraceError):
            TraceReader(data)


def test_v05_cpp_reader_agrees_on_independently_computed_payload_digest(tmp_path):
    checker = Path(__file__).resolve().parents[2] / "build/release/tiplog_trace_check"
    if not checker.is_file():
        pytest.skip("C++ release checker must be built for the cross-language P1 gate")
    path = tmp_path / "python-written.tpl"
    make_trace(path)
    outcome = subprocess.run([str(checker), str(path)], capture_output=True, text=True, check=True)
    result = json.loads(outcome.stdout)
    digest = 14695981039346656037
    for value in b"A\0\1E":
        digest = ((digest ^ value) * 1099511628211) & ((1 << 64) - 1)
    assert result["record_count"] == 3
    assert result["payload_bytes"] == 4
    assert result["topic_count"] == 2
    assert result["payload_fnv1a64"] == digest


def test_v05_empty_trace_and_atomic_abort(tmp_path):
    empty = tmp_path / "empty.tpl"
    with TraceWriter(empty, "00" * 32):
        pass
    with TraceReader(empty) as reader:
        assert list(reader) == []
        assert reader.dictionary == {}
    with pytest.raises(ValueError):
        with TraceWriter(tmp_path / "aborted.tpl", "00" * 32):
            raise ValueError("intentional failure")
    assert not (tmp_path / "aborted.tpl").exists()
    assert not (tmp_path / "aborted.tpl.partial").exists()


def test_v05_rejects_whitespace_shortened_sha256(tmp_path):
    with pytest.raises(ValueError):
        TraceWriter(tmp_path / "invalid.tpl", "00" * 31 + "  ")
