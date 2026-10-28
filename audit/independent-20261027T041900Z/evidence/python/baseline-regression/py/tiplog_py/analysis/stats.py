"""Seeded percentile bootstrap without treating paired runs as independent.

The resampling unit is explicit. These are descriptive uncertainty estimates
under the measured experimental design, not a correction for host/setup bias.
"""

import hashlib
from collections.abc import Mapping, Sequence

import numpy as np

RESAMPLES = 10_000


def stable_seed(seed: int, label: str) -> int:
    """Derive a deterministic seed independent of Python's randomized hash()."""
    digest = hashlib.sha256(f"{seed}\0{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _values(values: Sequence[float], *, positive=False) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 1 or not len(result):
        raise ValueError("observations must be a nonempty one-dimensional sequence")
    if not np.isfinite(result).all() or (positive and np.any(result <= 0)):
        raise ValueError("observations must be finite" + (" and positive" if positive else ""))
    return result


def median_summary(values: Sequence[float], *, seed: int, resamples=RESAMPLES) -> dict:
    """Median, IQR, range, n and a seeded 95% percentile-bootstrap interval.

    Quantiles use NumPy's linear interpolation. Missing observations are not
    accepted; the caller accounts for failures before selecting a metric.
    """
    data = _values(values)
    if not isinstance(resamples, int) or resamples <= 0:
        raise ValueError("resamples must be a positive integer")
    generator = np.random.default_rng(seed)
    medians = np.empty(resamples)
    # Bound temporary storage even for large repetition counts.
    chunk_size = max(1, min(1000, 1_000_000 // len(data)))
    if np.all(data == data[0]):
        # Every one of the prescribed resamples has this exact median.
        medians.fill(data[0])
    else:
        for offset in range(0, resamples, chunk_size):
            count = min(chunk_size, resamples - offset)
            indices = generator.integers(0, len(data), (count, len(data)))
            medians[offset:offset + count] = np.median(data[indices], axis=1)
    q1, q3 = np.quantile(data, [.25, .75])
    low, high = np.quantile(medians, [.025, .975])
    mean = float(np.mean(data))
    return {
        "n": len(data), "median": float(np.median(data)),
        "q1": float(q1), "q3": float(q3), "iqr": float(q3 - q1),
        "min": float(np.min(data)), "max": float(np.max(data)),
        "ci95_low": float(low), "ci95_high": float(high),
        "bootstrap_resamples": resamples, "bootstrap_seed": seed,
        "bootstrap_unit": "observation", "mean": mean,
        "sample_sd": float(np.std(data, ddof=1)) if len(data) > 1 else None,
        "cv": (float(np.std(data, ddof=1) / abs(mean))
               if len(data) > 1 and mean else None),
    }


def paired_ratio(numerator: Mapping[str, Sequence[float]],
                 denominator: Mapping[str, Sequence[float]], *, seed: int,
                 resamples=RESAMPLES) -> dict:
    """Ratio of medians with entire paired blocks resampled together.

    Each key identifies one independently repeated paired round. A block can
    contain multiple observations (e.g. a fixed reader cohort); all survive each
    resampling occurrence. Missing rounds, empty blocks and invalid times are
    errors, never an implicit unpaired fallback. Failed outcome handling belongs
    to :func:`summarize.paired_comparisons`, which withholds incomplete ratios.
    """
    if not numerator or set(numerator) != set(denominator):
        raise ValueError("paired arms require identical nonempty round identities")
    if not isinstance(resamples, int) or resamples <= 0:
        raise ValueError("resamples must be a positive integer")
    keys = sorted(numerator)
    top = [_values(numerator[key], positive=True) for key in keys]
    bottom = [_values(denominator[key], positive=True) for key in keys]
    ratio = float(np.median(np.concatenate(top)) / np.median(np.concatenate(bottom)))
    generator = np.random.default_rng(seed)
    ratios = np.empty(resamples)
    # Equal-sized blocks use a vectorized path; ragged blocks retain their full
    # observations by concatenation rather than averaging per-round medians.
    if len({len(value) for value in top}) == 1 and len({len(value) for value in bottom}) == 1:
        a, b = np.stack(top), np.stack(bottom)
        chunk_size = max(1, min(1000, 1_000_000 // (a.size + b.size)))
        for offset in range(0, resamples, chunk_size):
            count = min(chunk_size, resamples - offset)
            indices = generator.integers(0, len(keys), (count, len(keys)))
            ratios[offset:offset + count] = (
                np.median(a[indices].reshape(count, -1), axis=1)
                / np.median(b[indices].reshape(count, -1), axis=1))
    else:
        for index in range(resamples):
            selected = generator.integers(0, len(keys), len(keys))
            ratios[index] = (np.median(np.concatenate([top[item] for item in selected]))
                             / np.median(np.concatenate([bottom[item] for item in selected])))
    low, high = np.quantile(ratios, [.025, .975])
    return {"ratio": ratio, "ci95_low": float(low), "ci95_high": float(high),
            "paired_rounds": len(keys), "numerator_n": sum(map(len, top)),
            "denominator_n": sum(map(len, bottom)), "bootstrap_seed": seed,
            "bootstrap_resamples": resamples, "bootstrap_unit": "whole_paired_round"}
