"""Audit: Python parser/router/trace tests, including cross-language checks.

Run from an isolated copy:  TIPLOG_ROOT=<copy> TIPLOG_BUILD=<copy>/build/release \
    <venv>/bin/python -m pytest -p no:cacheprovider audit/tests/py
Cross-language tests call the C++ tiplog_walk / tiplog_trace_check binaries.
"""

import io
import os
from pathlib import Path
import random
import struct
import subprocess
import sys

import pytest

ROOT = Path(os.environ.get("TIPLOG_ROOT", Path(__file__).resolve().parents[3]))
BUILD = Path(os.environ.get("TIPLOG_BUILD", ROOT / "build" / "release"))
sys.path.insert(0, str(ROOT / "py"))

from tiplog_py.itch.protocol import LENGTHS, BinaryFileReader, FramingError  # noqa: E402
from tiplog_py.itch import __main__ as itch_cli  # noqa: E402
from tiplog_py.itch.routing import Router  # noqa: E402
from tiplog_py.trace.format import TraceError, TraceReader, TraceWriter  # noqa: E402

KINDS = list(LENGTHS)


def random_stream(rng: random.Random, count: int, terminate: bool) -> tuple[bytes, list[bytes]]:
    frames, payloads = [], []
    for _ in range(count):
        kind = rng.choice(KINDS)
        body = bytes([ord(kind)]) + bytes(rng.randrange(256) for _ in range(LENGTHS[kind] - 1))
        payloads.append(body)
        frames.append(struct.pack(">H", len(body)) + body)
    if terminate:
        frames.append(b"\0\0")
    return b"".join(frames), payloads


class Dribble(io.RawIOBase):
    """Return short reads of random size, like a slow pipe."""

    def __init__(self, data: bytes, rng: random.Random):
        self.data, self.offset, self.rng = data, 0, rng

    def readable(self):
        return True

    def read(self, size=-1):
        if size == 0 or self.offset >= len(self.data):
            return b""
        n = self.rng.randrange(1, 9)  # short but nonzero reads until real EOF
        chunk = self.data[self.offset:self.offset + n]
        self.offset += len(chunk)
        return chunk


@pytest.mark.parametrize("seed", range(300))
def test_binaryfile_reader_is_chunk_invariant(seed):
    rng = random.Random(seed)
    data, payloads = random_stream(rng, rng.randrange(0, 50), rng.random() < 0.5)
    for chunk_size in (2, 3, 7, 51, 4 * 1024 * 1024):
        reader = BinaryFileReader(io.BytesIO(data), chunk_size=chunk_size)
        assert list(reader) == payloads
        assert reader.message_count == len(payloads)
        assert reader.total_uncompressed_bytes == len(data)


@pytest.mark.parametrize("seed", range(100))
def test_binaryfile_reader_short_reads_do_not_fake_eof(seed):
    """A short (but nonzero) read is not EOF; only b'' is EOF (BufferedReader-free stream)."""
    rng = random.Random(seed)
    data, payloads = random_stream(rng, rng.randrange(1, 30), False)
    stream = Dribble(data, rng)
    reader = BinaryFileReader(stream, chunk_size=64)
    try:
        assert list(reader) == payloads
    except FramingError as error:  # pragma: no cover - documents a defect if hit
        pytest.fail(f"short read misreported as framing error: {error}")


@pytest.mark.parametrize("seed", range(200))
def test_binaryfile_truncation_always_raises(seed):
    rng = random.Random(seed)
    data, _ = random_stream(rng, rng.randrange(1, 20), False)
    cut = rng.randrange(1, len(data))
    framed_ends = set()
    position = 0
    while position < len(data):
        position += 2 + struct.unpack_from(">H", data, position)[0]
        framed_ends.add(position)
    reader = BinaryFileReader(io.BytesIO(data[:cut]), chunk_size=5)
    if cut in framed_ends:
        list(reader)
        assert reader.incomplete and not reader.terminated
    else:
        with pytest.raises(FramingError):
            list(reader)


@pytest.mark.skipif(not (BUILD / "tiplog_walk").exists(), reason="C++ build not available")
@pytest.mark.parametrize("seed", range(60))
def test_cpp_walker_agrees_with_python_reader(seed, tmp_path):
    """CC-6 at small scale: independent C++ and Python framing agree per type."""
    import json
    rng = random.Random(10_000 + seed)
    data, payloads = random_stream(rng, rng.randrange(0, 200), rng.random() < 0.5)
    source = tmp_path / "stream.bin"
    source.write_bytes(data)
    result = subprocess.run([str(BUILD / "tiplog_walk"), str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    cpp = json.loads(result.stdout)
    python_counts = {}
    for payload in payloads:
        python_counts[chr(payload[0])] = python_counts.get(chr(payload[0]), 0) + 1
    assert cpp["message_count"] == len(payloads)
    assert {k: v["count"] for k, v in cpp["by_type"].items()} == python_counts
    assert cpp["terminated"] == data.endswith(b"\0\0")


def _write_trace(path: Path, rng: random.Random) -> None:
    with TraceWriter(path, "ab" * 32) as writer:
        for _ in range(rng.randrange(0, 30)):
            topic = f"t/{rng.randrange(5)}/{rng.choice(['x', 'é', 'y/z'])}"
            writer.append(topic, bytes(rng.randrange(256) for _ in range(rng.randrange(60))),
                          rng.randrange(2 ** 63))


@pytest.mark.skipif(not (BUILD / "tiplog_trace_check").exists(), reason="C++ build not available")
@pytest.mark.parametrize("seed", range(400))
def test_python_and_cpp_trace_readers_agree_on_mutations(seed, tmp_path):
    """Differential acceptance: the Python writer/reader and the C++ reader must
    accept and reject exactly the same (possibly corrupted) trace files."""
    rng = random.Random(seed)
    path = tmp_path / "t.mdt"
    _write_trace(path, rng)
    data = bytearray(path.read_bytes())
    if seed % 4:
        for _ in range(rng.randrange(1, 4)):
            choice = rng.randrange(3)
            if choice == 0 and data:
                data[rng.randrange(len(data))] = rng.randrange(256)
            elif choice == 1 and data:
                del data[rng.randrange(len(data)):]
            else:
                data.insert(rng.randrange(len(data) + 1), rng.randrange(256))
    path.write_bytes(bytes(data))
    try:
        TraceReader(bytes(data))
        python_ok = True
    except TraceError:
        python_ok = False
    except Exception as error:  # any other type is itself a robustness finding
        pytest.fail(f"Python TraceReader raised {type(error).__name__}: {error}")
    cpp = subprocess.run([str(BUILD / "tiplog_trace_check"), str(path)], capture_output=True, text=True)
    assert cpp.returncode in (0, 2), cpp.stderr
    assert (cpp.returncode == 0) == python_ok, (seed, python_ok, cpp.stderr)


def _r_message(locate: int, symbol: bytes) -> bytes:
    body = bytearray(39)
    body[0] = ord("R")
    body[1:3] = locate.to_bytes(2, "big")
    body[11:19] = symbol
    return bytes(body)


def test_router_unknown_locate_and_k_routing():
    router = Router()
    add = bytearray(36)
    add[0] = ord("A")
    add[1:3] = (7).to_bytes(2, "big")
    add[24:32] = b"ZZZZ    "
    assert router.route(bytes(add)) == "itch/_unmapped/L7/A"
    router.route(_r_message(7, b"AB.C    "))
    assert router.route(bytes(add)) == "itch/AB.C/add/anon"
    assert router.summary()["symbol_mismatches"] == 1  # ZZZZ != AB.C


def test_red02_blank_symbol_aborts_with_framing_error_and_offset(tmp_path):
    """RED-02 (AUD-005). ARCHITECTURE 12: malformed ITCH aborts in strict mode
    *with a byte offset*. A Stock Directory message with an all-space symbol is
    malformed; the converter must raise FramingError carrying .offset.
    Baseline: routing.encode_symbol raises a plain ValueError('empty stock
    symbol') with no offset, so this test fails."""
    stream = struct.pack(">H", 12) + b"S" + bytes(11)
    stream += struct.pack(">H", 39) + _r_message(1, b"        ")
    source = tmp_path / "blank.itch"
    source.write_bytes(stream)
    argv = ["convert", str(source), "--output", str(tmp_path / "out.mdt"),
            "--start", "0", "--end", "86400000000000"]
    with pytest.raises(FramingError) as caught:
        itch_cli.main(argv)
    assert caught.value.offset in (14, 16)  # R frame length prefix or payload start
