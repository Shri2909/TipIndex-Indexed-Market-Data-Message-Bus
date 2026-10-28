"""Little-endian trace format; original project format, not Nasdaq framing."""

from dataclasses import dataclass
import hashlib
import mmap
import os
import tempfile
from pathlib import Path
import struct
from typing import Iterator


MAGIC = b"TPLTRC\0\1"
HEADER = struct.Struct("<8sIIQQQQ16s")
RECORD = struct.Struct("<IHHQ")
DICT_ENTRY = struct.Struct("<IH")
U32 = struct.Struct("<I")


class TraceError(ValueError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def path_bytes(path: str) -> bytes:
    if not path or any(not segment for segment in path.split("/")) or "\0" in path:
        raise TraceError("topic paths require nonempty segments and no NUL")
    encoded = path.encode("utf-8")
    if len(encoded) > 4096 or path.count("/") + 1 > 128:
        raise TraceError("topic path exceeds resource limit (4096 UTF-8 bytes / 128 segments)")
    return encoded


@dataclass(frozen=True, slots=True)
class TraceRecord:
    topic_id: int
    payload: bytes
    ts_ns: int
    flags: int = 0


class TraceWriter:
    def __init__(self, path: str | Path, source_sha256: str):
        if len(source_sha256) != 64:
            raise ValueError("source SHA-256 must contain 64 hex characters")
        try:
            source_bytes = bytes.fromhex(source_sha256)
        except ValueError as exc:
            raise ValueError("source SHA-256 must be hexadecimal") from exc
        if len(source_bytes) != 32:
            raise ValueError("source SHA-256 must decode to exactly 32 bytes")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, partial = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".partial", dir=self.path.parent)
        self.partial = Path(partial)
        self.stream = os.fdopen(fd, "w+b")
        try:
            self.stream.write(bytes(HEADER.size))
        except BaseException:
            self.stream.close()
            self.partial.unlink(missing_ok=True)
            raise
        self.source_prefix = int.from_bytes(source_bytes[:8], "little")
        self.topics: dict[str, int] = {}
        self.count = 0
        self.closed = False

    def append(self, topic: str, payload: bytes, ts_ns: int) -> None:
        if self.closed:
            raise ValueError("writer closed")
        if len(payload) > 65535 or not 0 <= ts_ns < 2**64:
            raise TraceError("record field exceeds representation")
        topic_id = self.topics.get(topic)
        if topic_id is None:
            path_bytes(topic)
            topic_id = len(self.topics) + 1
            if topic_id >= 2**32:
                raise TraceError("topic id exceeds u32")
            self.topics[topic] = topic_id
        self.stream.write(RECORD.pack(topic_id, len(payload), 0, ts_ns))
        self.stream.write(payload)
        self.stream.write(bytes((-len(payload)) % 8))
        self.count += 1

    def finish(self) -> None:
        if self.closed:
            return
        dict_offset = self.stream.tell()
        self.stream.write(U32.pack(len(self.topics)))
        for path, topic_id in self.topics.items():
            encoded = path_bytes(path)
            self.stream.write(DICT_ENTRY.pack(topic_id, len(encoded)))
            self.stream.write(encoded)
        dict_length = self.stream.tell() - dict_offset
        self.stream.seek(0)
        self.stream.write(HEADER.pack(MAGIC, 1, 0, self.count, dict_offset,
                                      dict_length, self.source_prefix, bytes(16)))
        self.stream.close()
        self.partial.replace(self.path)
        self.closed = True

    def abort(self) -> None:
        if not self.closed:
            self.stream.close()
            self.partial.unlink(missing_ok=True)
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.finish() if exc_type is None else self.abort()


class TraceReader:
    """Validate all boundaries and metadata before exposing any record."""

    def __init__(self, source: str | Path | bytes | bytearray):
        self._stream = None
        self._map = None
        if isinstance(source, (bytes, bytearray)):
            self.data = source
        else:
            self._stream = open(source, "rb")
            if self._stream.seek(0, 2) == 0:
                self._stream.close()
                raise TraceError("truncated file header")
            self._stream.seek(0)
            self._map = mmap.mmap(self._stream.fileno(), 0, access=mmap.ACCESS_READ)
            self.data = self._map
        try:
            self._validate()
        except BaseException:
            self.close()
            raise

    def _validate(self) -> None:
        data = self.data
        if len(data) < HEADER.size:
            raise TraceError("truncated file header")
        magic, version, flags, count, offset, length, prefix, reserved = HEADER.unpack_from(data)
        if magic != MAGIC or version != 1:
            raise TraceError("unsupported trace magic/version")
        if flags or any(reserved):
            raise TraceError("nonzero trace flags/reserved bytes")
        if offset < HEADER.size or offset % 8 or offset > len(data) or length != len(data) - offset:
            raise TraceError("invalid dictionary offset/length or trailing bytes")
        if length < U32.size:
            raise TraceError("truncated dictionary count")
        self.record_count = count
        self.dict_offset = offset
        self.source_sha256_prefix = prefix
        cursor = offset + U32.size
        dictionary_count = U32.unpack_from(data, offset)[0]
        if dictionary_count > (len(data) - cursor) // (DICT_ENTRY.size + 1):
            raise TraceError("impossible dictionary count")
        self.dictionary: dict[int, str] = {}
        paths: set[str] = set()
        for _ in range(dictionary_count):
            if cursor + DICT_ENTRY.size > len(data):
                raise TraceError("truncated dictionary entry")
            topic_id, path_length = DICT_ENTRY.unpack_from(data, cursor)
            cursor += DICT_ENTRY.size
            if path_length == 0 or cursor + path_length > len(data):
                raise TraceError("truncated/empty dictionary path")
            try:
                path = data[cursor:cursor + path_length].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise TraceError("invalid UTF-8 dictionary path") from exc
            path_bytes(path)
            cursor += path_length
            if topic_id == 0 or topic_id in self.dictionary or path in paths:
                raise TraceError("zero/duplicate dictionary id or path")
            self.dictionary[topic_id] = path
            paths.add(path)
        if cursor != len(data):
            raise TraceError("extra dictionary bytes")
        if count > (offset - HEADER.size) // RECORD.size:
            raise TraceError("impossible record count")
        cursor = HEADER.size
        for _ in range(count):
            if cursor + RECORD.size > offset:
                raise TraceError("truncated record header")
            topic_id, payload_length, record_flags, _ts_ns = RECORD.unpack_from(data, cursor)
            end = cursor + RECORD.size + payload_length
            aligned_end = (end + 7) & ~7
            if record_flags or topic_id not in self.dictionary:
                raise TraceError("unsupported record flags or unknown topic")
            if aligned_end > offset or any(data[end:aligned_end]):
                raise TraceError("truncated record or nonzero alignment padding")
            cursor = aligned_end
        if cursor != offset:
            raise TraceError("record count does not cover record region")

    def __iter__(self) -> Iterator[TraceRecord]:
        cursor = HEADER.size
        for _ in range(self.record_count):
            topic_id, length, flags, ts_ns = RECORD.unpack_from(self.data, cursor)
            begin = cursor + RECORD.size
            yield TraceRecord(topic_id, self.data[begin:begin + length], ts_ns, flags)
            cursor = (begin + length + 7) & ~7

    def close(self) -> None:
        if self._map is not None:
            self._map.close()
            self._map = None
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
