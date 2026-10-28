"""Bounds-checked ITCH fields and BinaryFILE framing.

Independent implementation from Nasdaq's published tables, not third-party code.
S05: TotalView-ITCH 5.0 §§1.1–1.8; S06: BinaryFILE 1.0 §§1.1–1.2.
Prices stay unsigned scaled integers; this parser never rounds through a float.
"""

from collections.abc import Iterator
from typing import BinaryIO


LENGTHS = {"S": 12, "R": 39, "H": 25, "Y": 20, "L": 26,
           "V": 35, "W": 12, "K": 28, "J": 35, "h": 21,
           "A": 36, "F": 40, "E": 31, "C": 36, "X": 23,
           "D": 19, "U": 35, "P": 44, "Q": 40, "B": 19,
           "I": 50, "N": 20, "O": 48}
LENGTHS_BY_BYTE = {ord(kind): length for kind, length in LENGTHS.items()}
SYMBOL_OFFSETS = {kind: 11 for kind in "RHYKJhNO"}
SYMBOL_OFFSETS.update({"L": 15, "A": 24, "F": 24, "P": 24,
                       "Q": 19, "I": 28})

# name, byte offset, width, kind (integer or right-space-padded ASCII).
_STOCK = [("stock", 11, 8, "a")]
_ORDER = [("order_reference", 11, 8, "i")]
_ADD = _ORDER + [("side", 19, 1, "a"), ("shares", 20, 4, "i"),
                 ("stock", 24, 8, "a"), ("price", 32, 4, "i")]
FIELDS = {
    "S": [("event_code", 11, 1, "a")],
    "R": _STOCK + [("market_category", 19, 1, "a"), ("financial_status", 20, 1, "a"),
                    ("round_lot_size", 21, 4, "i"), ("round_lots_only", 25, 1, "a"),
                    ("issue_classification", 26, 1, "a"), ("issue_subtype", 27, 2, "a"),
                    ("authenticity", 29, 1, "a"), ("short_sale_threshold", 30, 1, "a"),
                    ("ipo_flag", 31, 1, "a"), ("luld_tier", 32, 1, "a"),
                    ("etp_flag", 33, 1, "a"), ("etp_leverage", 34, 4, "i"),
                    ("inverse", 38, 1, "a")],
    "H": _STOCK + [("trading_state", 19, 1, "a"), ("reserved", 20, 1, "a"),
                    ("reason", 21, 4, "a")],
    "Y": _STOCK + [("reg_sho_action", 19, 1, "a")],
    "L": [("mpid", 11, 4, "a"), ("stock", 15, 8, "a"),
          ("primary_market_maker", 23, 1, "a"), ("market_maker_mode", 24, 1, "a"),
          ("market_participant_state", 25, 1, "a")],
    "V": [("level_1", 11, 8, "i"), ("level_2", 19, 8, "i"), ("level_3", 27, 8, "i")],
    "W": [("breached_level", 11, 1, "a")],
    "K": _STOCK + [("ipo_release_time", 19, 4, "i"), ("ipo_release_qualifier", 23, 1, "a"),
                    ("ipo_price", 24, 4, "i")],
    "J": _STOCK + [("reference_price", 19, 4, "i"), ("upper_price", 23, 4, "i"),
                    ("lower_price", 27, 4, "i"), ("extension", 31, 4, "i")],
    "h": _STOCK + [("market_code", 19, 1, "a"), ("halt_action", 20, 1, "a")],
    "A": _ADD,
    "F": _ADD + [("attribution", 36, 4, "a")],
    "E": _ORDER + [("executed_shares", 19, 4, "i"), ("match_number", 23, 8, "i")],
    "C": _ORDER + [("executed_shares", 19, 4, "i"), ("match_number", 23, 8, "i"),
                    ("printable", 31, 1, "a"), ("execution_price", 32, 4, "i")],
    "X": _ORDER + [("cancelled_shares", 19, 4, "i")],
    "D": _ORDER,
    "U": [("original_order_reference", 11, 8, "i"), ("new_order_reference", 19, 8, "i"),
          ("shares", 27, 4, "i"), ("price", 31, 4, "i")],
    "P": _ADD + [("match_number", 36, 8, "i")],
    "Q": [("shares", 11, 8, "i"), ("stock", 19, 8, "a"), ("cross_price", 27, 4, "i"),
          ("match_number", 31, 8, "i"), ("cross_type", 39, 1, "a")],
    "B": [("match_number", 11, 8, "i")],
    "I": [("paired_shares", 11, 8, "i"), ("imbalance_shares", 19, 8, "i"),
          ("imbalance_direction", 27, 1, "a"), ("stock", 28, 8, "a"),
          ("far_price", 36, 4, "i"), ("near_price", 40, 4, "i"),
          ("current_reference_price", 44, 4, "i"), ("cross_type", 48, 1, "a"),
          ("price_variation_indicator", 49, 1, "a")],
    "N": _STOCK + [("interest_flag", 19, 1, "a")],
    "O": _STOCK + [("open_eligibility", 19, 1, "a"), ("minimum_price", 20, 4, "i"),
                    ("maximum_price", 24, 4, "i"), ("near_price", 28, 4, "i"),
                    ("near_execution_time", 32, 8, "i"), ("lower_collar", 40, 4, "i"),
                    ("upper_collar", 44, 4, "i")],
}


class FramingError(ValueError):
    """A malformed stream, with an absolute decompressed byte offset."""

    def __init__(self, message: str, offset: int):
        self.offset = offset
        super().__init__(f"{message} at uncompressed byte {offset}")


def validate_message(payload: bytes, offset: int = 0) -> str:
    if not payload:
        raise FramingError("empty ITCH payload", offset)
    kind = chr(payload[0])
    expected = LENGTHS.get(kind)
    if expected is None:
        raise FramingError(f"unsupported ITCH type 0x{payload[0]:02x}", offset)
    if len(payload) != expected:
        raise FramingError(f"type {kind} length {len(payload)} != {expected}", offset)
    symbol_offset = SYMBOL_OFFSETS.get(kind)
    if symbol_offset is not None and not payload[symbol_offset:symbol_offset + 8].rstrip(b" "):
        raise FramingError("empty stock symbol", offset)
    return kind


def parse_message(payload: bytes) -> dict[str, str | int]:
    kind = validate_message(payload)
    fields: dict[str, str | int] = {
        "type": kind,
        "locate": int.from_bytes(payload[1:3], "big"),
        "tracking": int.from_bytes(payload[3:5], "big"),
        "ts_ns": int.from_bytes(payload[5:11], "big"),
    }
    for name, start, size, encoding in FIELDS[kind]:
        data = payload[start:start + size]
        if encoding == "i":
            fields[name] = int.from_bytes(data, "big")
        else:
            try:
                fields[name] = data.decode("ascii").rstrip(" ")
            except UnicodeDecodeError as exc:
                raise FramingError(f"non-ASCII {name}", start) from exc
    return fields


class BinaryFileReader:
    """Read bounded chunks; never retain a full day in memory.

    Missing terminator is a valid, explicitly incomplete input. Partial length or
    payload, unknown ITCH types, wrong lengths and bytes after terminator fail.
    Underlying gzip errors propagate; reaching the real EOF checks gzip CRC.
    """

    def __init__(self, stream: BinaryIO, *, chunk_size: int = 4 * 1024 * 1024,
                 limit_bytes: int | None = None):
        if chunk_size < 2 or (limit_bytes is not None and limit_bytes < 1):
            raise ValueError("positive byte limit and chunk_size >= 2 required")
        self.stream = stream
        self.chunk_size = chunk_size
        self.limit_bytes = limit_bytes
        self.total_uncompressed_bytes = 0
        self.message_count = 0
        self.terminated = False
        self.incomplete = True
        self.limited = False

    def __iter__(self) -> Iterator[bytes]:
        pending = b""
        base = 0
        while True:
            chunk = self.stream.read(self.chunk_size)
            data = pending + chunk
            end = len(data)
            position = 0
            while position + 2 <= end:
                length = (data[position] << 8) | data[position + 1]
                offset = base + position
                if length == 0:
                    self.total_uncompressed_bytes = offset + 2
                    self.terminated = True
                    self.incomplete = False
                    # Read to the physical EOF: reject trailing bytes and force
                    # decompressor checksum/trailer validation.
                    if position + 2 != end or self.stream.read(1):
                        raise FramingError("bytes after BinaryFILE terminator", offset + 2)
                    return
                if position + 2 + length > end:
                    break
                kind = data[position + 2]
                expected = LENGTHS_BY_BYTE.get(kind)
                if expected is None:
                    raise FramingError(f"unsupported ITCH type 0x{kind:02x}", offset + 2)
                if expected != length:
                    raise FramingError(f"type {chr(kind)} length {length} != {expected}", offset)
                position += 2
                payload = data[position:position + length]
                position += length
                symbol_offset = SYMBOL_OFFSETS.get(chr(kind))
                if symbol_offset is not None and not payload[symbol_offset:symbol_offset + 8].rstrip(b" "):
                    raise FramingError("empty stock symbol", offset + 2)
                self.total_uncompressed_bytes = base + position
                self.message_count += 1
                yield payload
                if self.limit_bytes is not None and self.total_uncompressed_bytes >= self.limit_bytes:
                    self.limited = True
                    return
            if not chunk:
                self.total_uncompressed_bytes = base + end
                if end - position == 1:
                    raise FramingError("truncated BinaryFILE length", base + position)
                if end - position:
                    raise FramingError("truncated BinaryFILE payload", base + position)
                return
            pending = data[position:]
            base += position
