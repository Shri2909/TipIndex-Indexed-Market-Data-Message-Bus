"""V01/V02: hand-encoded Nasdaq golden messages, no converter schema helpers."""

import gzip
import io
import struct

import pytest

from tiplog_py.itch import BinaryFileReader, FramingError, LENGTHS, parse_message


TIMESTAMP = 34_200_123_456_789


def header(kind, locate=17, timestamp=TIMESTAMP):
    return struct.pack(">cHH", kind.encode("ascii"), locate, 0x1234) + timestamp.to_bytes(6, "big")


# The independently written struct layouts below are read from S05 §§1.1–1.8.
# Golden values exercise byte order, mixed widths, alpha padding and scaled prices.
GOLDENS = [
    ("S", b"O", {"event_code": "O"}),
    ("R", b"AB.C    " + b"QN" + struct.pack(">I", 100) + b"NCEE PN1Y" + struct.pack(">I", 3) + b"N",
     {"stock": "AB.C", "market_category": "Q", "round_lot_size": 100, "etp_leverage": 3, "inverse": "N"}),
    ("H", struct.pack(">8scc4s", b"AB.C    ", b"T", b" ", b"T1  "),
     {"stock": "AB.C", "trading_state": "T", "reason": "T1"}),
    ("Y", b"AB.C    1", {"stock": "AB.C", "reg_sho_action": "1"}),
    ("L", b"NSDQAB.C    YNA", {"mpid": "NSDQ", "stock": "AB.C", "primary_market_maker": "Y", "market_participant_state": "A"}),
    ("V", struct.pack(">QQQ", 123456789012, 234567890123, 345678901234),
     {"level_1": 123456789012, "level_2": 234567890123, "level_3": 345678901234}),
    ("W", b"2", {"breached_level": "2"}),
    ("K", b"IPO.X   " + struct.pack(">IcI", 36001, b"A", 1234500),
     {"stock": "IPO.X", "ipo_release_time": 36001, "ipo_release_qualifier": "A", "ipo_price": 1234500}),
    ("J", b"AB.C    " + struct.pack(">IIII", 1234500, 1300000, 1100000, 2),
     {"stock": "AB.C", "reference_price": 1234500, "upper_price": 1300000, "lower_price": 1100000, "extension": 2}),
    ("h", b"AB.C    QH", {"stock": "AB.C", "market_code": "Q", "halt_action": "H"}),
    ("A", struct.pack(">QcI8sI", 0x0102030405060708, b"S", 1234, b"AB.C    ", 1234567),
     {"order_reference": 0x0102030405060708, "side": "S", "shares": 1234, "stock": "AB.C", "price": 1234567}),
    ("F", struct.pack(">QcI8sI4s", 0x0102030405060708, b"B", 4321, b"AB.C    ", 7654321, b"NSDQ"),
     {"order_reference": 0x0102030405060708, "side": "B", "shares": 4321, "price": 7654321, "attribution": "NSDQ"}),
    ("E", struct.pack(">QIQ", 0x0102030405060708, 99, 0x0807060504030201),
     {"order_reference": 0x0102030405060708, "executed_shares": 99, "match_number": 0x0807060504030201}),
    ("C", struct.pack(">QIQcI", 0x0102030405060708, 101, 0x0807060504030201, b"N", 1234567),
     {"executed_shares": 101, "match_number": 0x0807060504030201, "printable": "N", "execution_price": 1234567}),
    ("X", struct.pack(">QI", 0x0102030405060708, 102),
     {"order_reference": 0x0102030405060708, "cancelled_shares": 102}),
    ("D", struct.pack(">Q", 0x0102030405060708), {"order_reference": 0x0102030405060708}),
    ("U", struct.pack(">QQII", 0x0102030405060708, 0x0807060504030201, 103, 1234567),
     {"original_order_reference": 0x0102030405060708, "new_order_reference": 0x0807060504030201, "shares": 103, "price": 1234567}),
    ("P", struct.pack(">QcI8sIQ", 0, b"B", 104, b"AB.C    ", 1234567, 0x0807060504030201),
     {"order_reference": 0, "side": "B", "shares": 104, "stock": "AB.C", "price": 1234567, "match_number": 0x0807060504030201}),
    ("Q", struct.pack(">Q8sIQc", 2**33 + 105, b"AB.C    ", 1234567, 0x0807060504030201, b"O"),
     {"shares": 2**33 + 105, "stock": "AB.C", "cross_price": 1234567, "match_number": 0x0807060504030201, "cross_type": "O"}),
    ("B", struct.pack(">Q", 0x0807060504030201), {"match_number": 0x0807060504030201}),
    ("I", struct.pack(">QQc8sIIIcc", 2**33 + 106, 107, b"B", b"AB.C    ", 1230000, 1234000, 1234567, b"O", b"L"),
     {"paired_shares": 2**33 + 106, "imbalance_shares": 107, "imbalance_direction": "B", "stock": "AB.C", "far_price": 1230000, "near_price": 1234000, "current_reference_price": 1234567, "cross_type": "O", "price_variation_indicator": "L"}),
    ("N", b"AB.C    A", {"stock": "AB.C", "interest_flag": "A"}),
    ("O", struct.pack(">8scIIIQII", b"IPO.X   ", b"Y", 100000, 200000, 150000, 34_199_999_999_999, 120000, 180000),
     {"stock": "IPO.X", "open_eligibility": "Y", "minimum_price": 100000, "maximum_price": 200000, "near_price": 150000, "near_execution_time": 34_199_999_999_999, "lower_collar": 120000, "upper_collar": 180000}),
]


@pytest.mark.parametrize("kind,body,expected", GOLDENS, ids=[row[0] for row in GOLDENS])
def test_v01_all_23_types_decode_golden_fields(kind, body, expected):
    payload = header(kind, 0 if kind in "SVWK" else 17) + body
    assert len(payload) == LENGTHS[kind]
    actual = parse_message(payload)
    assert actual["type"] == kind
    assert actual["locate"] == (0 if kind in "SVWK" else 17)
    assert actual["tracking"] == 0x1234
    assert actual["ts_ns"] == TIMESTAMP
    for field, value in expected.items():
        assert actual[field] == value, field


def framed(messages, terminated=True):
    return b"".join(len(message).to_bytes(2, "big") + message for message in messages) + (b"\0\0" if terminated else b"")


@pytest.mark.parametrize("chunk_size", [2, 3, 7, 13, 65536])
def test_v02_chunk_boundaries_and_exact_byte_count(chunk_size):
    messages = [header(kind, 0 if kind in "SVWK" else 17) + body for kind, body, _ in GOLDENS]
    data = framed(messages)
    reader = BinaryFileReader(io.BytesIO(data), chunk_size=chunk_size)
    assert list(reader) == messages
    assert reader.message_count == 23
    assert reader.total_uncompressed_bytes == len(data)
    assert reader.terminated and not reader.incomplete


def test_v02_missing_terminator_is_explicitly_incomplete():
    data = framed([header("S", 0) + b"O"], False)
    reader = BinaryFileReader(io.BytesIO(data))
    assert len(list(reader)) == 1
    assert reader.total_uncompressed_bytes == len(data)
    assert reader.incomplete and not reader.terminated


@pytest.mark.parametrize("data,pattern", [
    (b"\x00", "truncated.*length"),
    (b"\x00\x0cS\0\0", "truncated.*payload"),
    (b"\x00\x01?", "unsupported ITCH"),
    (b"\x00\x01S", "length 1 != 12"),
    (b"\0\0\x00", "after.*terminator"),
    (b"\0\0" + framed([header("S", 0) + b"O"]), "after.*terminator"),
])
def test_v02_malformed_framing_fails_with_absolute_offset(data, pattern):
    with pytest.raises(FramingError, match=pattern) as failure:
        list(BinaryFileReader(io.BytesIO(data), chunk_size=3))
    assert failure.value.offset >= 0


def test_v02_buffered_limit_never_splits_an_event():
    data = framed([header("S", 0) + b"O"] * 5)
    reader = BinaryFileReader(io.BytesIO(data), limit_bytes=15)
    assert len(list(reader)) == 2
    assert reader.total_uncompressed_bytes == 28
    assert reader.limited and not reader.terminated


def test_v02_gzip_crc_and_truncation_errors_propagate():
    data = gzip.compress(framed([header("S", 0) + b"O"]))
    broken_crc = bytearray(data)
    broken_crc[-8] ^= 1
    for broken in (broken_crc, data[:-4]):
        with pytest.raises((gzip.BadGzipFile, EOFError)):
            list(BinaryFileReader(gzip.GzipFile(fileobj=io.BytesIO(broken))))


def test_v02_concatenated_gzip_members_are_counted_as_one_stream():
    message = header("S", 0) + b"O"
    content = gzip.compress(framed([message], False)) + gzip.compress(b"\0\0")
    reader = BinaryFileReader(gzip.GzipFile(fileobj=io.BytesIO(content)))
    assert list(reader) == [message]
    assert reader.total_uncompressed_bytes == 16
