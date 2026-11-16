"""The statistics of Tech Spec §6.6: one question-cluster bootstrap, Holm, Wilson.

Every bootstrapped metric here is built from per-question arrays: a resample of the questions
is a row of counts W[b, q] (how many times question q was drawn), so a ratio metric
sum_q num[q] / sum_q den[q] becomes (W @ num) / (W @ den) for all resamples at once. One seeded
matrix serves every metric (EvalKit D-37).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from citewatch.schemas import Interval

RESAMPLES = 10_000
ALPHA = 0.05  # pre-registered: two-sided, family-wise, Holm (docs/preregistration.md)
Z95 = 1.959963984540054

Arr = NDArray[np.float64]


def resample_matrix(n_questions: int, seed: int, resamples: int = RESAMPLES) -> Arr:
    """W[b, q]: how often question q appears in resample b (each row sums to n_questions)."""
    if n_questions <= 0:
        return np.zeros((resamples, 0))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_questions, size=(resamples, n_questions))
    w = np.zeros((resamples, n_questions))
    np.add.at(w, (np.repeat(np.arange(resamples), n_questions), idx.ravel()), 1.0)
    return w


def interval(point: float, values: Arr, *, n: int, k: int | None = None) -> Interval:
    """Percentile 95% interval of the resampled values; widened to include the point if a
    skewed resample distribution leaves it outside (a known limit, never a silent clamp of the
    point itself)."""
    v = values[np.isfinite(values)]
    if v.size == 0:
        lo = hi = point
    else:
        lo, hi = (float(x) for x in np.percentile(v, [2.5, 97.5]))
    lo, hi = min(lo, point), max(hi, point)
    return Interval(point=point, lo=lo, hi=hi, n=n, k=k)


def percentiles(values: Arr) -> tuple[Arr, Arr]:
    """Column-wise 2.5th and 97.5th percentiles of (B, K) resampled values, ignoring NaN."""
    if values.shape[1] == 0:
        return np.zeros(0), np.zeros(0)
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            lo, hi = np.nanpercentile(values, [2.5, 97.5], axis=0)
    return lo, hi


def make_interval(point: float, lo: float, hi: float, *, n: int, k: int | None = None) -> Interval:
    lo = point if not math.isfinite(lo) else lo
    hi = point if not math.isfinite(hi) else hi
    return Interval(point=point, lo=min(lo, point), hi=max(hi, point), n=n, k=k)


def boot_ratio(w: Arr, num: Arr, den: Arr) -> Arr:
    """Resampled values of sum(num)/sum(den): (B,) for 1-D num, (B, K) for (Q, K) num."""
    top = w @ num
    bottom = w @ den
    with np.errstate(divide="ignore", invalid="ignore"):
        if top.ndim == 2:
            return top / bottom[:, None]
        return top / bottom


def p_two_sided(diffs: Arr) -> float:
    """Bootstrap p-value for a difference of zero: twice the smaller tail, at most 1."""
    d = diffs[np.isfinite(diffs)]
    if d.size == 0:
        return 1.0
    # (count + 1) / (B + 1): a bootstrap p-value is never exactly 0 (v1 L3)
    below = (float(np.sum(d <= 0)) + 1) / (d.size + 1)
    above = (float(np.sum(d >= 0)) + 1) / (d.size + 1)
    return min(1.0, 2 * min(below, above))


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm-adjusted p-values (step-down, monotone, capped at 1), in the input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def wilson(k: int, n: int, z: float = Z95) -> Interval:
    """Wilson score interval for k successes in n trials (§6.6, small proportions)."""
    if n <= 0:
        return Interval(point=0.0, lo=0.0, hi=0.0, n=0, k=0)
    if not 0 <= k <= n:
        raise ValueError(f"k must be within 0..n, got {k} of {n}")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return Interval(
        point=p, lo=max(0.0, min(p, centre - half)), hi=min(1.0, max(p, centre + half)), n=n, k=k
    )


def jaccard(a: set[str], b: set[str]) -> float | None:
    """|a ∩ b| / |a ∪ b|; None when both are empty (§6.4 excludes those questions)."""
    union = a | b
    return None if not union else len(a & b) / len(union)
