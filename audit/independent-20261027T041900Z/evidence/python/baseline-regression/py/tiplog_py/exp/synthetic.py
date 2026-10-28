"""Independently generated synthetic schedule; specified integer RNG is portable."""
from __future__ import annotations
import bisect
import csv
import hashlib
import math
from pathlib import Path
import numpy as np
from .oracle import INDEX_DTYPE

MASK = (1 << 64)-1


class SplitMix64:
    def __init__(self, seed): self.state = seed & MASK
    def next(self):
        self.state = (self.state + 0x9e3779b97f4a7c15) & MASK
        value = self.state
        value = ((value ^ (value >> 30)) * 0xbf58476d1ce4e5b9) & MASK
        value = ((value ^ (value >> 27)) * 0x94d049bb133111eb) & MASK
        return value ^ (value >> 31)
    def bounded(self, bound):
        if not 0 < bound <= 1 << 64: raise ValueError('invalid random bound')
        threshold = ((1 << 64)-bound) % bound
        while True:
            value = self.next()
            if value >= threshold: return value % bound


def empirical_mix(path: Path) -> list[tuple[int, int]]:
    rows = list(csv.DictReader(path.open()))
    lengths = [(int(row.get('payload_bytes', row.get('payload_length', row.get('length')))),
                int(row['count'])) for row in rows]
    return lengths


def schedule(*, records: int, partitions: int, zipf: float, run_length: int,
             seed: int, mix: list[tuple[int, int]]):
    """Returns compact arrays and synthetic bytes; each call is a fresh schedule.

    RNG order: first/switch→owner, event, payload type; the first row has no
    switch draw. Switches force a different owner; a stationary circle coupling
    preserves the Zipf marginal while giving actual owner runs geometric mean L.
    Events have probabilities .01/.09/.90. Bounded draws use rejection.
    """
    if records < 0 or partitions < 1 or run_length < 1 or not math.isfinite(zipf) or zipf < 0:
        raise ValueError('invalid synthetic schedule')
    rng = SplitMix64(seed)
    cdf = []
    if zipf:
        weights = [float(rank) ** -zipf for rank in range(1, partitions+1)]
        cumulative = 0.0
        for weight in weights:
            cumulative += weight
            cdf.append(cumulative)
        total = cumulative
        cdf = [value/total for value in cdf]
        cdf[-1] = 1.0
        maximum_interval = max(right-left for left, right in zip([0.0]+cdf[:-1], cdf))
        if maximum_interval >= .5:
            raise ValueError('stationary no-self Zipf coupling needs max probability <.5')
    mix_cdf, total = [], 0
    for length, count in mix:
        if not 0 <= length <= 65535 or count <= 0: raise ValueError('invalid payload mix')
        total += count
        mix_cdf.append(total)
    payloads = {(base, length): bytes((base+byte*31)&255 for byte in range(length))
                for base in range(256) for length, _count in mix}
    rows = np.empty(records, dtype=INDEX_DTYPE)
    # Array bytearray is mutable for ctypes but never changed once exposed.
    data = bytearray()
    owner = 0
    for index in range(records):
        seq = index+1
        if seq == 1:
            owner = (bisect.bisect_right(cdf, (rng.next() >> 11) * (2.0 ** -53))
                     if zipf else rng.bounded(partitions))
        elif rng.bounded(run_length) == 0:
            previous = owner
            if not zipf:
                if partitions < 2:
                    raise ValueError('different-owner runs require at least2 partitions')
                owner = rng.bounded(partitions-1)
                if owner >= previous: owner += 1
            else:
                left = cdf[previous-1] if previous else 0.0
                right = cdf[previous]
                unit1 = (rng.next() >> 11)*(2.0**-53)
                unit2 = (rng.next() >> 11)*(2.0**-53)
                point = min(math.nextafter(right, left), left+unit1*(right-left))
                shift = maximum_interval+unit2*(1-2*maximum_interval)
                rotated = point+shift
                if rotated >= 1: rotated -= 1
                owner = bisect.bisect_right(cdf, rotated)
            if owner == previous or owner >= partitions:
                raise ValueError('stationary no-self coupling failed')
        draw = rng.bounded(100)
        event = 0 if draw < 1 else 1 if draw < 10 else 2
        length = mix[bisect.bisect_right(mix_cdf, rng.bounded(total))][0]
        offset = len(data)
        data.extend(payloads[((seed+seq*17)&255, length)])
        rows[index] = (offset, seq*1000, owner*3+event+1, length, (16+length+7)&~7)
    topics = {owner*3+event+1: f'synth/p{owner}/e{event}'
              for owner in range(partitions) for event in range(3)}
    return data, rows, topics


def schedule_summary(rows: np.ndarray, partitions: int) -> dict:
    owners = (rows['topic'].astype(np.uint64)-1)//3
    events = (rows['topic'].astype(np.uint64)-1)%3
    counts = np.bincount(owners.astype(np.int64), minlength=partitions)
    ranked_counts = np.sort(counts)[::-1]
    runs = int(np.count_nonzero(owners[1:] != owners[:-1]))+int(len(owners)>0)
    return {'records': len(rows), 'observed_owner_runs': runs,
            'observed_run_mean': len(rows)/runs if runs else None,
            'owner_top1_count': int(ranked_counts[0]), 'owner_top10_count': int(ranked_counts[:10].sum()),
            'owner_counts_sha256': hashlib.sha256(counts.astype('<u8').tobytes()).hexdigest(),
            'event_counts': [int(np.count_nonzero(events == event)) for event in range(3)]}
