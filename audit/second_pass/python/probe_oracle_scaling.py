"""Diagnostic cost probe; not a controlled project performance measurement."""
import json
import statistics
import time
import numpy as np
from tiplog_py.exp.oracle import retained_layout

observations = []
for count in (4000, 8000, 16000, 32000, 64000):
    samples = []
    for _ in range(3):
        start = time.perf_counter()
        result = retained_layout(np.full(count, 24, dtype="u8"), 64)
        samples.append(time.perf_counter() - start)
    observations.append({"records": count, "ring_capacity": 64,
        "pad_items": result["pad_items"],
        "suffix_elements_incremented": count * (count - 2) // 4,
        "median_seconds": statistics.median(samples), "samples_seconds": samples})
print(json.dumps(observations, indent=2))
