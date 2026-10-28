"""Scalar reference and optional independently compiled byte-only acceleration."""
from __future__ import annotations
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211
MASK = (1 << 64) - 1


def scalar_fnv(state: int, seq: int, payload: bytes) -> int:
    for value in struct.pack('<Q', seq) + payload:
        state = ((state ^ value) * FNV_PRIME) & MASK
    return state


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def build_accelerator(directory: Path | None = None) -> dict:
    """Build separately from measured blocks and preserve the actual provenance."""
    directory = directory or ROOT / 'build/python-oracle'
    directory.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('hash_bytes.c')
    compiler = shutil.which('cc')
    if not compiler:
        raise RuntimeError('C compiler required for independent oracle byte acceleration')
    binary = directory / 'libtiplog_oracle_bytes.so'
    command = [compiler, '-std=c11', '-O2', '-fPIC', '-shared', '-Wall', '-Wextra',
               '-Werror', str(source), '-o', str(binary)]
    child = subprocess.run(command, capture_output=True, text=True, check=False)
    record = {'argv': command, 'returncode': child.returncode,
              'stdout': child.stdout, 'stderr': child.stderr,
              'compiler_version': subprocess.check_output([compiler, '--version'], text=True),
              'source': str(source), 'source_sha256': sha_file(source)}
    if child.returncode:
        raise RuntimeError(json.dumps(record))
    record.update(binary=str(binary), binary_sha256=sha_file(binary))
    (directory / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


class ByteAccelerator:
    def __init__(self, binary: Path | None = None):
        binary = binary or ROOT / 'build/python-oracle/libtiplog_oracle_bytes.so'
        self.library = ctypes.CDLL(str(binary))
        ptr = ctypes.c_void_p
        self.library.tiplog_oracle_fnv.argtypes = [ptr, ptr, ptr, ptr, ctypes.c_size_t, ctypes.c_uint64]
        self.library.tiplog_oracle_fnv.restype = ctypes.c_uint64
        self.library.tiplog_oracle_copy.argtypes = [ptr, ptr, ptr, ctypes.c_size_t, ptr]
        self.library.tiplog_oracle_copy.restype = ctypes.c_size_t

    def update(self, data, offsets, lengths, seqs, state: int, payload_hash) -> int:
        offsets = np.ascontiguousarray(offsets, dtype='<u8')
        lengths = np.ascontiguousarray(lengths, dtype='<u2')
        seqs = np.ascontiguousarray(seqs, dtype='<u8')
        if not (len(offsets) == len(lengths) == len(seqs)):
            raise ValueError('byte-vector lengths disagree')
        if len(offsets) and (np.any(offsets > len(data)) or
                            np.any(lengths.astype('u8') > len(data) - offsets)):
            raise ValueError('payload outside mapped source')
        source = (ctypes.c_ubyte * len(data)).from_buffer(data)
        size = int(lengths.sum(dtype=np.uint64))
        output = (ctypes.c_ubyte * size)()
        arguments = [ctypes.addressof(source), offsets.ctypes.data, lengths.ctypes.data]
        copied = self.library.tiplog_oracle_copy(*arguments, len(offsets), output)
        if copied != size:
            raise RuntimeError('byte accelerator copy size disagreement')
        payload_hash.update(output)
        result = int(self.library.tiplog_oracle_fnv(*arguments, seqs.ctypes.data,
                                                  len(seqs), state))
        del source
        return result
