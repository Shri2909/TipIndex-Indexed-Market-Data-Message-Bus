#!/usr/bin/env python3
"""Validate F-01 observations against an independent deterministic fixture.

The original analysis implementation is retained under results/f01 for historical
reproduction. This maintained entry point adds independent byte/position/mode
checks, then retains its summary schema and paired statistical calculations.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
_HISTORICAL = ROOT/'results/f01/summarize.py'
if hashlib.sha256(_HISTORICAL.read_bytes()).hexdigest() != 'd47350aba69e067ab6980b83afebd857e41e15158ccb32c2431caf096b252d55':
    raise ValueError('historical F01 statistical implementation changed')
_SPEC = importlib.util.spec_from_file_location('tiplog_historical_f01_summary', _HISTORICAL)
_OLD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_OLD)
IDENTITY = _OLD.IDENTITY
MASK = (1 << 64) - 1
SIZES = (0, 1, 17, 65, 129, 257)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(text):
    return json.loads(text, object_pairs_hook=_OLD.unique_object,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON: '+v)))


def natural(row, field, low=0, high=MASK):
    value = row[field]
    require(type(value) is int and low <= value <= high, 'invalid '+field)
    return value


@lru_cache(maxsize=64)
def fixture(n, seed, case, shape, k, stride):
    """Reconstruct publication without engine, registry, ring or C++ helpers."""
    lengths = (0,) if shape == 'small' else (64,) if shape == 'fixed' else SIZES
    spans = tuple((16+x+7)//8*8 for x in lengths)
    rounds, remainder = divmod(n, len(spans))
    data_bytes = rounds*sum(spans)+sum(spans[:remainder])
    ring_bytes = 1 << (max(4096, data_bytes+560)-1).bit_length()
    require(ring_bytes <= 128 << 20, 'independent fixture ring exceeds resource cap')
    checkpoint_bytes = (ring_bytes//4096+2)*8
    topics_bytes = (k+5)*4096
    # The declared pool policy reserves packed blocks plus two per possible
    # partition and one spare. The preflight counts 32-byte metadata, 1024 u32
    # entries, one sealed byte and a 16-byte heap node per block.
    blocks = (ring_bytes+16383)//16384+2*(k+5)+1
    pool_bytes = blocks*(32+4*1024+1+16)
    require(ring_bytes+checkpoint_bytes+pool_bytes+(k+5)*128+topics_bytes <= 128 << 20,
            'independent fixture preparation exceeds resource cap')
    pos = priming = 0
    if shape == 'wrapped-variable':
        target = (ring_bytes-data_bytes//2)//8*8
        # The primer emits 280-byte DATA followed by a final >=16-byte DATA.
        rounds, remainder = divmod(target, 280)
        priming = rounds+int(remainder >= 16)
        pos = rounds*280+(remainder if remainder >= 16 else 0)
    digest = 14695981039346656037
    outputs = candidates = pads = pad_bytes = selected_bytes = 0

    def hash_bytes(values):
        nonlocal digest
        for value in values:
            digest = ((digest ^ value)*1099511628211) & MASK

    for ordinal in range(n):
        size = spans[ordinal % len(spans)]
        room = ring_bytes-pos % ring_bytes
        if size > room:
            # seek_after starts at the first DATA, excluding a leading PAD.
            if ordinal:
                pads += 1
                pad_bytes += room
            pos += room
        selected = ordinal % stride == 0 or ordinal == n-1
        if selected:
            selected_bytes += size
            matched = case == 'dense' or (case == 'late-match' and ordinal == n-1) or (case == 'sparse' and candidates % 128 == 127)
            if matched:
                # intern("bench/p0/hit") registers bench, p0, hit; each new
                # partition subsequently contributes pN, hit, miss in that order.
                topic = 3+3*(candidates % k)
                length = lengths[ordinal % len(lengths)]
                for value in (priming+ordinal+1, pos, topic, length):
                    hash_bytes(value.to_bytes(8, 'little'))
                state = (seed ^ ((ordinal*0x9e3779b97f4a7c15) & MASK)) & MASK
                for _ in range(length):
                    state ^= state >> 12
                    state ^= (state << 25) & MASK
                    state ^= state >> 27
                    hash_bytes((((state*2685821657736338717) & MASK) >> 56,))
                outputs += 1
            candidates += 1
        pos += size
    return {'priming': priming, 'data_bytes': data_bytes, 'pads': pads,
            'pad_bytes': pad_bytes, 'selected_bytes': selected_bytes,
            'candidates': candidates, 'next_pos': pos,
            'ring_bytes':ring_bytes, 'checkpoint_bytes':checkpoint_bytes,
            'topics_bytes':topics_bytes, 'minimum_index_bytes':pool_bytes,
            'digest': {'outputs': outputs, 'fnv1a64': f'{digest:016x}'}}


def validate(row):
    require(isinstance(row, dict), 'raw row must be an object')
    n = natural(row, 'records', 1, 2_000_000)
    seed = natural(row, 'seed')
    k = natural(row, 'configured_partitions', 1, 65535)
    stride = natural(row, 'candidate_every', 1, 1024)
    natural(row, 'repetition')
    natural(row, 'calls', 1)
    natural(row, 'max_outputs', 1, 2_000_000)
    require(row['case'] in ('no-match', 'late-match', 'sparse', 'dense'), 'unknown case')
    require(row['shape'] in ('small', 'fixed', 'variable', 'wrapped-variable'), 'unknown shape')
    for field in ('fixture_reserved_bytes', 'fixture_selected_partitions', 'selected_partition_count',
                  'fixture_priming_records', 'fixture_data_bytes', 'fixture_pads_in_range',
                  'fixture_candidate_records', 'inspections_used', 'max_inspections_in_call',
                  'max_outputs_in_call', 'zero_output_calls', 'service_calls', 'peak_rss_bytes',
                  'fixture_build_ns', 'drain_elapsed_ns', 'drain_cpu_ns', 'open_elapsed_ns',
                  'index_reserved_bytes', 'ring_checkpoint_bytes', 'conservative_topics_bytes'):
        natural(row, field)
    for field in ('after_seq', 'next_pos'):
        natural(row['final_checkpoint'], field)
    natural(row['output_digest'], 'outputs')
    natural(row['oracle_digest'], 'outputs')
    model = fixture(n, seed, row['case'], row['shape'], k, stride)
    require(row['ring_checkpoint_bytes'] == model['checkpoint_bytes']
            and row['conservative_topics_bytes'] == model['topics_bytes']
            and row['index_reserved_bytes'] >= model['minimum_index_bytes']
            and row['fixture_reserved_bytes'] == model['ring_bytes']+model['checkpoint_bytes']
                +model['topics_bytes']+row['index_reserved_bytes'], 'inconsistent fixture resource accounting')
    for field, expected in (('fixture_priming_records', model['priming']),
                            ('fixture_data_bytes', model['data_bytes']),
                            ('fixture_pads_in_range', model['pads']),
                            ('fixture_candidate_records', model['candidates'])):
        require(row[field] == expected, 'independent fixture mismatch: '+field)
    require(row['output_digest'] == row['oracle_digest'] == model['digest'], 'independent publication digest mismatch')
    require(row['final_checkpoint'] == {'after_seq': n+model['priming'], 'next_pos': model['next_pos']},
            'independent final checkpoint mismatch')
    mode = row['mode']
    require(mode in ('scan', 'indexed', 'auto'), 'unknown configured mode')
    effective = mode if mode != 'auto' else ('indexed' if k <= 64 and model['candidates'] <= .25*n else 'scan')
    require(row['effective_mode'] == effective, 'configured/effective mode mismatch')
    require(row['selected_partition_count'] == (k if effective == 'indexed' else 0), 'planned partition count mismatch')
    budget = row['budget']
    require(isinstance(budget, str), 'invalid budget')
    if budget not in ('legacy', 'unlimited'):
        require(budget.isascii() and budget.isdecimal() and 0 < int(budget) <= MASK, 'invalid finite budget')
    key = _OLD.validate(row)
    work = row['poll_work']
    require(work['bytes_inspected'] == (model['selected_bytes'] if effective == 'indexed' else model['data_bytes']+model['pad_bytes']),
            'independent inspected-byte count mismatch')
    require(row['drain_elapsed_ns'] >= row['poll_latency_ns']['sum'] > 0, 'invalid poll/drain timing')
    for field in ('poll_latency_ns', 'victim_service_delay_ns', 'publisher_service_delay_ns'):
        sample = row[field]
        require(sample['sum'] <= sample['sample_count']*sample['max'], 'impossible sample sum')
        if sample['sample_count'] == 1:
            require(len({sample[x] for x in ('p50', 'p95', 'p99', 'max', 'sum')}) == 1, 'inconsistent singleton statistics')
    for field, expected in (('outputs_per_drain_second', model['digest']['outputs']*1e9/row['drain_elapsed_ns']),
                            ('fixture_records_per_poll_second', n*1e9/row['poll_latency_ns']['sum'])):
        value = row[field]
        require(type(value) in (int, float) and math.isfinite(value) and math.isclose(value, expected, rel_tol=1e-12),
                'inconsistent reported rate: '+field)
    return key


def summarize(paths):
    for path in paths:
        with Path(path).open() as stream:
            for number, line in enumerate(stream, 1):
                try:
                    validate(decode(line))
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(f'{path}:{number}: {error}') from error
    return _OLD.summarize(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = summarize(args.inputs)
    if args.output:
        target = args.output.resolve()
        require(any(target.is_relative_to(ROOT/name) for name in ('results/f01', 'build/f01')),
                'summary output must be beneath results/f01 or build/f01')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write('\n')
    print(json.dumps({'status': 'passed', 'validated_rows': result['validated_rows'], 'arms': len(result['arms'])}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('F01 summary: '+str(error), file=sys.stderr)
        raise SystemExit(1)
