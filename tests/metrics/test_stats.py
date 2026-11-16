"""MET-07: the §6.6 statistics against hand-computed cases."""

from __future__ import annotations

import numpy as np
import pytest

from citewatch.metrics.stats import (
    holm,
    jaccard,
    make_interval,
    p_two_sided,
    resample_matrix,
    wilson,
)


def test_wilson_matches_the_textbook_values():
    iv = wilson(5, 10)
    assert (
        iv.point == 0.5
        and iv.lo == pytest.approx(0.2366, abs=1e-4)
        and iv.hi == pytest.approx(0.7634, abs=1e-4)
    )
    zero = wilson(0, 20)
    assert zero.lo == 0.0 and zero.hi == pytest.approx(0.1611, abs=1e-4)
    assert wilson(0, 0).n == 0
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_holm_is_step_down_monotone_and_capped():
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert holm([0.5, 0.9]) == [1.0, 1.0]
    assert holm([]) == []


def test_one_seeded_resample_matrix():
    w = resample_matrix(7, seed=53, resamples=500)
    assert w.shape == (500, 7) and (w.sum(axis=1) == 7).all()
    assert np.array_equal(w, resample_matrix(7, seed=53, resamples=500))
    assert not np.array_equal(w, resample_matrix(7, seed=54, resamples=500))


def test_two_sided_bootstrap_p_value():
    assert p_two_sided(np.array([1.0] * 99 + [-1.0])) == pytest.approx(2 * 2 / 101)
    assert p_two_sided(np.array([1.0] * 100)) == pytest.approx(2 / 101)  # never exactly 0
    assert p_two_sided(np.array([0.0, 0.0])) == 1.0
    assert p_two_sided(np.array([np.nan])) == 1.0


def test_jaccard_and_intervals():
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert jaccard(set(), set()) is None
    iv = make_interval(0.5, 0.6, 0.9, n=4)
    assert iv.lo == 0.5 and iv.hi == 0.9  # a point outside the percentiles widens the interval
    assert make_interval(0.2, float("nan"), float("nan"), n=1).lo == 0.2
