"""Bounded independent scalar review of the Python retained-layout model."""
import itertools
import json

import numpy as np

from tiplog_py.exp.oracle import retained_layout

MAX = (1 << 64) - 1


def scalar(sizes, capacity):
    pos = 0
    pads, positions = [], []
    for size in sizes:
        room = capacity - pos % capacity
        if size > room:
            pads.append((pos, room))
            pos += room
        positions.append(pos)
        pos += size
    if pos > MAX:
        raise ValueError('overflow')
    cutoff = max(0, pos - capacity)
    unread = next((i for i, x in enumerate(positions) if x >= cutoff), len(sizes))
    tail = positions[unread] if unread < len(sizes) else pos
    for start, _size in pads:
        if cutoff <= start < tail:
            tail = start
    return dict(positions=positions, head_pos=pos, tail_pos=tail,
                head_seq=len(sizes) + 1, tail_seq=unread + 1,
                retained_data=len(sizes) - unread,
                pad_bytes=sum(size for _, size in pads), pad_items=len(pads))


cases = 0
for capacity in (8, 16, 64, 1 << 53, 1 << 54, 1 << 63):
    values = sorted(set((1, capacity // 2, capacity - 1, capacity)))
    for n in range(5):
        for sizes in itertools.product(values, repeat=n):
            cases += 1
            try:
                expected = scalar(sizes, capacity)
            except ValueError:
                try:
                    retained_layout(np.array(sizes, dtype='u8'), capacity)
                except ValueError:
                    continue
                raise AssertionError(('overflow accepted', sizes, capacity))
            actual = retained_layout(np.array(sizes, dtype='u8'), capacity)
            actual['positions'] = actual['positions'].tolist()
            assert actual == expected, (sizes, capacity, actual, expected)
print(json.dumps(dict(status='passed', cases=cases,
                      scope='scalar append/evict comparison, capacities through 2^63, sizes through capacity, all sequences of length 0..4')))
