"""MET-01..MET-08 on a study small enough to work out by hand (see conftest for the data)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citewatch.metrics import build_summary, write_summary
from citewatch.metrics.views import connect
from citewatch.schemas import StudySummary, load_questions, load_study_config

A, B = "claude-sonnet-5-5", "gpt-6.1-sol"


@pytest.fixture
def summary(tiny: Path) -> StudySummary:
    cfg = load_study_config(tiny / "study.yaml")
    return build_summary(tiny, cfg, load_questions(tiny / "questions.jsonl", cfg), resamples=400)


def pick(rows, **kw):
    out = [r for r in rows if all(getattr(r, k) == v for k, v in kw.items())]
    assert len(out) == 1, (kw, out)
    return out[0]


def test_presence_share_keeps_zero_citation_answers_and_drops_refusals(summary):
    nhs = pick(summary.share, publisher="nhs.uk", model=A, intent=None, run=1, kind="presence")
    assert nhs.share.point == pytest.approx(2 / 3) and nhs.share.n == 3 and nhs.share.k == 2
    assert (
        pick(
            summary.share, publisher="nhs.uk", model=B, intent=None, run=1, kind="presence"
        ).share.point
        == 0.5
    )


def test_weighted_share_uses_answers_with_citations_and_sums_to_one(summary):
    rows = [
        r
        for r in summary.share
        if r.model == B and r.intent is None and r.run == 1 and r.kind == "weighted"
    ]
    got = {r.publisher: r.share.point for r in rows}
    assert got == pytest.approx({"nhs.uk": 4 / 9, "x.com": 2 / 9, "bbc.co.uk": 1 / 3})
    assert sum(got.values()) == pytest.approx(1.0) and rows[0].share.n == 3


def test_intent_slices(summary):
    beta = pick(
        summary.share, publisher="bbc.co.uk", model=B, intent="beta", run=1, kind="presence"
    )
    assert beta.share.point == 0.5 and beta.share.n == 2


def test_citations_per_answer(summary):
    row = pick(summary.citations, model=A, intent=None, run=1)
    assert (
        row.unique_per_answer.point == 1.0 and row.zero_citation == 1 and row.raw_per_answer == 1.0
    )


def test_concentration(summary):
    row = pick(summary.concentration, model=B, run=1)
    assert row.top10_share.point == pytest.approx(1.0)
    assert row.hhi == pytest.approx((4 / 9) ** 2 + (2 / 9) ** 2 + (1 / 3) ** 2)


def test_freshness_excludes_and_counts_pages_modified_after_the_answer(summary):
    nhs = pick(summary.freshness, publisher="nhs.uk", model=None)
    assert nhs.median_lag_days == 323 and nhs.dated_pages == 3 and nhs.modified_after_answer == 0
    bbc = pick(summary.freshness, publisher="bbc.co.uk", model=None)
    assert bbc.dated_pages == 0 and bbc.median_lag_days is None and bbc.modified_after_answer == 4


def test_stale_rates_and_undated_answers(summary):
    a = pick(summary.stale, model=A, intent=None, definition="primary")
    assert a.rate.point == 0.5 and a.rate.n == 4 and a.rate.k == 2 and a.undated == 0
    b = pick(summary.stale, model=B, intent=None, definition="primary")
    assert b.rate.point == 0.0 and b.rate.n == 2 and b.undated == 2


def test_nhs_overdue(summary):
    row = pick(summary.nhs_overdue, model=None)
    assert row.share.point == pytest.approx(4 / 6) and row.share.k == 4


def test_overlap_self_overlap_and_normalised(summary):
    assert pick(
        summary.overlap, kind="cross_model", intent=None, run=1
    ).value.point == pytest.approx(1 / 6)
    run2 = pick(summary.overlap, kind="cross_model", intent=None, run=2)
    assert run2.value.point == pytest.approx(1 / 3) and run2.value.n == 3
    assert summary.error_counts["overlap_excluded"]["cross_model:all:run2"] == 1
    assert pick(summary.overlap, kind="self", model=A, intent=None).value.point == pytest.approx(
        0.5
    )
    assert pick(summary.overlap, kind="self", model=B, intent=None).value.point == pytest.approx(
        2.5 / 3
    )
    assert pick(summary.overlap, kind="normalised", intent=None).value.point == pytest.approx(0.375)


def test_stability(summary):
    assert pick(summary.stability, model=B, metric="self_jaccard").value.point == pytest.approx(
        2.5 / 3
    )
    change = pick(summary.stability, model=A, metric="share_change", publisher="bbc.co.uk")
    assert change.value.point == pytest.approx(1 / 4 - 1 / 3)  # run 2 has t-004 valid: 1 of 4


def test_comparisons_use_shared_questions_with_holm(summary):
    rows = [r for r in summary.comparisons if r.run == 1]
    got = {r.publisher: r.difference.point for r in rows}
    assert got == pytest.approx({"nhs.uk": 0.0, "bbc.co.uk": 0.0, "x.com": -1 / 3})
    assert all(r.p_holm >= r.p_value for r in rows) and not any(r.separated for r in rows)


def test_coverage_errors_and_spend(summary):
    assert summary.coverage.k == 4 and summary.coverage.n == 6
    assert summary.error_counts[A]["refusal"] == 1 and summary.error_counts[A]["zero_citation"] == 2
    assert summary.spend_usd == 0.75 and summary.runs == (1, 2)


def test_summary_is_byte_identical_on_a_rerun_and_validates(tiny: Path):
    cfg = load_study_config(tiny / "study.yaml")
    qs = load_questions(tiny / "questions.jsonl", cfg)
    first = write_summary(tiny, build_summary(tiny, cfg, qs, resamples=300)).read_bytes()
    second = write_summary(tiny, build_summary(tiny, cfg, qs, resamples=300)).read_bytes()
    assert first == second
    StudySummary.model_validate(json.loads(first))
    assert json.loads(first)["generated_at"].startswith(
        "2026-11-21"
    )  # from the data, not the clock


def test_duckdb_views_reproduce_presence_share(tiny: Path, summary):
    con = connect(tiny)
    for run, model, pub, k, n, share in con.execute("SELECT * FROM presence").fetchall():
        row = pick(summary.share, publisher=pub, model=model, intent=None, run=run, kind="presence")
        assert (row.share.k, row.share.n) == (k, n) and row.share.point == pytest.approx(share)
