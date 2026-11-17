"""MET-01..MET-08 on a study small enough to work out by hand (see conftest for the data)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citewatch.handcheck import dates_fingerprint
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
    # a page dated after the answer is dated and newest: excluded from lag only (v1 M1)
    b = pick(summary.stale, model=B, intent=None, definition="primary")
    assert b.rate.point == 0.0 and b.rate.n == 4 and b.undated == 0


def test_nhs_overdue(summary):
    row = pick(summary.nhs_overdue, model=None)  # NHS pairs only; no review date = not overdue
    assert row.share.point == pytest.approx(4 / 7) and row.share.k == 4 and row.share.n == 7


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


# --- verifier pass 1 -----------------------------------------------------------------------------


def _edit(tiny: Path, name: str, fn) -> None:
    p = tiny / "data" / name
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x]
    p.write_text("".join(json.dumps(r) + "\n" for r in fn(rows)), encoding="utf-8")


def _score(tiny: Path) -> StudySummary:
    cfg = load_study_config(tiny / "study.yaml")
    return build_summary(tiny, cfg, load_questions(tiny / "questions.jsonl", cfg), resamples=200)


def test_a_newer_page_dated_after_the_answer_keeps_an_answer_fresh(tiny: Path):
    """v1 M1: t-001 on Claude cites a 1,054-day page and a page modified after the answer."""

    def swap(rows):
        for r in rows:
            if (r["run"], r["question_id"], r["model"]) == (1, "t-001", A) and r["url"].endswith(
                "nhs.uk/a"
            ):
                r["url"] = "https://nhs.uk/b"
        return rows

    _edit(tiny, "citations.jsonl", swap)
    assert pick(_score(tiny).stale, model=A, intent=None, definition="primary").rate.point == 0.5


def test_stale_and_overdue_boundaries_are_strict(tiny: Path):
    """v1 L8: exactly 365 days is not stale; a review due on the answer day is not overdue."""

    def pages(rows):
        for r in rows:
            if r["url"] == "https://nhs.uk/b":
                r["effective_date"] = "2025-11-20"  # 365 days before 2026-11-20
            if r["url"] == "https://nhs.uk/a":
                r["review_due"] = "2026-11-20"
        return rows

    _edit(tiny, "page_meta.jsonl", pages)
    s = _score(tiny)
    assert pick(s.stale, model=A, intent=None, definition="primary").rate.k == 0
    assert pick(s.stale, model=A, intent=None, definition="secondary").rate.k == 0
    assert pick(s.nhs_overdue, model=None).share.k == 0


def test_a_transport_error_leaves_the_denominator(tiny: Path):
    def err(rows):
        for r in rows:
            if (r["run"], r["question_id"], r["model"]) == (1, "t-002", B):
                r["error"] = "transport"
        return rows

    _edit(tiny, "answers.jsonl", err)
    s = _score(tiny)
    assert (
        pick(s.share, publisher="nhs.uk", model=B, intent=None, run=1, kind="presence").share.n == 3
    )
    assert s.error_counts[B]["transport"] == 1


def test_spend_counts_only_the_scored_runs(tiny: Path, summary):
    assert summary.spend_usd == 0.75  # runs 1 and 2; run 0 and fixture spend are not counted


def test_top_lists_include_every_publisher_tied_at_the_cut():
    from citewatch.metrics.compute import top_with_ties

    shares = {f"p{i:02d}": 0.1 for i in range(15)} | {"big": 0.9}
    assert len(top_with_ties(shares, 10)) == 16
    assert top_with_ties({"a": 0.5, "b": 0.4, "c": 0.4}, 2) == ["a", "b", "c"]
    assert top_with_ties({"a": 0.5}, 10) == ["a"]


def test_undated_pages_are_counted_by_outcome(summary):
    assert summary.error_counts["undated_pages"] == {"ok": 2}


# --- verifier pass 2 -----------------------------------------------------------------------------


def test_comparison_ties_are_exact_whatever_float_rounding_does(tmp_path: Path):
    """v2 M1: 1/5 + 2/5 != 3/5 + 0 in floats; both publishers have 3 citing answers."""
    from citewatch.metrics.compute import Ctx, comparisons
    from citewatch.metrics.data import Answer, Cite, StudyData
    from citewatch.metrics.stats import resample_matrix

    at = __import__("datetime").datetime(2026, 11, 20, tzinfo=__import__("datetime").UTC)

    def ans(q, m, pubs):
        return Answer(1, q, m, "alpha", False, at, True, False, False, False, False,
                      cites=[Cite(f"https://{p}/{q}", p) for p in pubs])  # fmt: skip

    lead = [f"lead{i}.com" for i in range(9)]
    answers = []
    for i in range(5):
        q = f"q-00{i}"
        answers.append(
            ans(q, A, [*lead, *(["split.com"] if i == 0 else []), *(["solo.com"] if i < 3 else [])])
        )
        answers.append(ans(q, B, [*lead, *(["split.com"] if i in (1, 2) else [])]))
    data = StudyData([], answers, {}, 0.0, at)
    rows = comparisons(Ctx(data, resample_matrix(5, 53, 50), 365))
    assert {"split.com", "solo.com"} <= {r.publisher for r in rows}


def test_an_nhs_page_missing_from_page_meta_counts_as_not_overdue(tiny: Path):
    _edit(tiny, "page_meta.jsonl", lambda rows: [r for r in rows if r["url"] != "https://nhs.uk/c"])
    s = _score(tiny)
    assert pick(s.nhs_overdue, model=None).share.n == 7
    assert s.error_counts["nhs_no_review_date"] == {"missing": 1}


def test_spend_ignores_another_studys_ledger_lines(tiny: Path):
    p = tiny / "data" / "spend-ledger.jsonl"
    p.write_text(
        p.read_text(encoding="utf-8") + '{"run_id": "other:run-1", "spent_usd": 5.0}\n',
        encoding="utf-8",
    )
    assert _score(tiny).spend_usd == 0.75


def test_stability_top_list_includes_ties():
    from citewatch.metrics.compute import top_with_ties

    counts = {f"p{i:02d}": 2.0 for i in range(12)}
    assert len(top_with_ties(counts, 10)) == 12


def test_pooled_top_sets_cut_at_the_kth_share_with_ties():
    import numpy as np

    from citewatch.metrics.compute import _top_sets

    pubs = [f"p{i:02d}" for i in range(25)]
    row = np.array([25 - i for i in range(25)], dtype=float)
    assert _top_sets(row, pubs, 20)[0] == set(pubs[:20])
    row[20] = row[19]
    assert _top_sets(row, pubs, 20)[0] == set(pubs[:21])


def test_support_and_date_accuracy_join_the_summary_when_present(tiny: Path):
    data = tiny / "data"
    ref = "1:t-001:claude-sonnet-5-5:1"
    (data / "support_verdicts.jsonl").write_text(
        json.dumps({"citation_ref": ref, "judge": "opus", "verdict": "supported"}) + "\n",
        encoding="utf-8",
    )
    (data / "support_label_key.jsonl").write_text(
        json.dumps({"id": "s01", "citation_ref": ref}) + "\n", encoding="utf-8"
    )
    (data / "support_labels.jsonl").write_text(
        json.dumps({"id": "s01", "label": "supported"}) + "\n", encoding="utf-8"
    )
    (data / "hand_sample.jsonl").write_text(
        json.dumps({"url": "https://nhs.uk/a", "stratum": "schema_org", "role": "dated"}) + "\n",
        encoding="utf-8",
    )
    (data / "hand_labels.jsonl").write_text(
        json.dumps(
            {
                "url": "https://nhs.uk/a",
                "true_modified": "2026-01-03",
                "not_determinable": False,
                "dates_version": dates_fingerprint(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    s = _score(tiny)
    assert {(r.judge, r.support_rate.k) for r in s.support} == {("opus", 1), ("hand", 1)}
    overall = pick(s.date_accuracy, source="overall")
    assert overall.within_7_days.k == 1 and overall.exact.k == 0
    assert s.check_methods["date_accuracy"].startswith("agent-checked, owner-approved")
    assert s.check_methods["support_hand"].startswith("owner-labelled")
    assert s.error_counts["hand_dates"] == {
        "labels": 1,
        "stale_labels": 0,
        "unjudgeable": 0,
        "checker_could_not_load": 0,
    }


def _hand_labels(data: Path, versions: list[str]) -> None:
    rows = [
        {"url": f"https://nhs.uk/p{i}", "stratum": "schema_org", "role": "dated"}
        for i in range(len(versions))
    ]
    (data / "hand_sample.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    labels = [
        {
            "url": r["url"],
            "true_modified": "2026-01-03",
            "not_determinable": False,
            "dates_version": v,
        }
        for r, v in zip(rows, versions, strict=True)
    ]
    (data / "hand_labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labels), "utf-8")


def test_stale_date_labels_block_the_accuracy_rows_even_with_a_fresh_first_row(tiny: Path):
    """D-6: one fresh row placed first must not let 54 stale rows through (M3.3 pass 1, H1/H2)."""
    _hand_labels(tiny / "data", [dates_fingerprint()] + ["old"] * 54)
    s = _score(tiny)
    assert s.date_accuracy == ()
    assert s.error_counts["hand_dates"]["blocked"] == 1
    assert s.error_counts["hand_dates"]["stale_labels"] == 54
    assert "date_accuracy" not in s.check_methods


def test_twenty_five_fresh_labels_publish_and_only_they_are_scored(tiny: Path):
    _hand_labels(tiny / "data", ["old"] * 30 + [dates_fingerprint()] * 25)
    s = _score(tiny)
    assert s.error_counts["hand_dates"] == {
        "labels": 55,
        "stale_labels": 30,
        "unjudgeable": 0,
        "checker_could_not_load": 0,
    }
    assert sum(r.within_7_days.n for r in s.date_accuracy if r.source != "overall") <= 25


def test_duplicate_or_unsampled_fresh_labels_do_not_satisfy_the_25_page_rule(tiny: Path):
    """D-6 counts distinct sampled pages (M3.3 pass 2, M1/M2)."""
    data = tiny / "data"
    _hand_labels(data, ["old"] * 55)
    fresh = {"true_modified": "2026-01-03", "not_determinable": False}
    extra = [dict(fresh, url="https://nhs.uk/p0", dates_version=dates_fingerprint())] * 25
    extra += [
        dict(fresh, url=f"https://elsewhere.org/{i}", dates_version=dates_fingerprint())
        for i in range(25)
    ]
    with (data / "hand_labels.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in extra))
    s = _score(tiny)
    assert s.date_accuracy == () and s.error_counts["hand_dates"]["blocked"] == 1


def test_pages_the_checker_could_not_load_are_counted_and_never_scored(tiny: Path):
    data = tiny / "data"
    _hand_labels(data, [dates_fingerprint()] * 3)
    rows = [json.loads(x) for x in (data / "hand_labels.jsonl").read_text("utf-8").splitlines()]
    rows[0].update(true_modified=None, not_determinable=True, checker_loaded=False)
    (data / "hand_labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    s = _score(tiny)
    counts = s.error_counts["hand_dates"]
    assert counts["checker_could_not_load"] == 1 and counts["unjudgeable"] == 0


def test_finalise_refuses_stale_date_labels_whatever_the_row_order(tiny: Path, capsys):
    from citewatch.cli import main

    data = tiny / "data"
    (data / "support_labels.jsonl").write_text("", encoding="utf-8")
    _hand_labels(data, [dates_fingerprint()] + ["old"] * 54)
    code = main(["score", "--finalise", "--study", str(tiny), "--json"])
    assert code == 2 and "date resolver changed" in capsys.readouterr().out


def test_finalise_refuses_before_the_labels_are_imported(tiny: Path, capsys):
    from citewatch.cli import main

    code = main(["score", "--finalise", "--study", str(tiny), "--json"])
    assert code == 2 and "import the owner's labels" in capsys.readouterr().out
