"""SUP-04..06: support rates, agreement and kappa, the fetch gap, finalise."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citewatch.schemas import SupportVerdict
from citewatch.support.report import (
    finalise,
    gaps,
    kappa,
    kappa_interval,
    load_hand_labels,
    support_rows,
    write_gaps,
)

C, G = "claude-sonnet-5-5", "gpt-6.1-sol"


def v(ref: str, judge: str, ok: bool) -> SupportVerdict:
    return SupportVerdict(
        citation_ref=ref, judge=judge, verdict="supported" if ok else "unsupported"
    )


def test_kappa_matches_hand_computed_values():
    assert kappa([True, True, False, False], [True, True, False, False]) == 1.0
    # po = 0.5, pa = pb = 0.5, pe = 0.5 -> 0
    assert kappa([True, False, True, False], [True, True, False, False]) == 0.0
    # po = 0.8; pa = 0.6, pb = 0.4; pe = 0.24 + 0.24 = 0.48; k = 0.32 / 0.52
    a = [True, True, True, False, False]
    b = [True, True, False, False, False]
    assert kappa(a, b) == pytest.approx((0.8 - 0.48) / 0.52)
    assert kappa([True, True], [True, True]) is None and kappa([], []) is None


def test_kappa_interval_is_seeded_and_contains_the_point():
    a = [True, False] * 10 + [True] * 5
    b = [True, False] * 10 + [False] * 5
    one, two = (
        kappa_interval(a, b, seed=51, resamples=500),
        kappa_interval(a, b, seed=51, resamples=500),
    )
    assert one == two and one.lo <= one.point <= one.hi and one.n == 25


def test_support_rows_per_model_and_judge_with_hand_labels():
    refs = [f"1:v-00{i}:{C}:1" for i in range(4)] + [f"1:v-00{i}:{G}:1" for i in range(2)]
    verdicts = [v(r, "opus", i % 2 == 0) for i, r in enumerate(refs)]
    hand = {
        refs[0]: "supported",
        refs[1]: "supported",
        refs[2]: "cant_tell",
        refs[3]: "unsupported",
        refs[4]: "supported",
    }
    rows = {(r.model, r.judge): r for r in support_rows(verdicts, hand, seed=51)}
    opus_c = rows[(C, "opus")]
    assert (opus_c.support_rate.k, opus_c.support_rate.n) == (2, 4)
    assert opus_c.hand_agreement == pytest.approx(
        2 / 3
    )  # refs 0, 1, 3 judged by both; 0 and 3 agree
    hand_c = rows[(C, "hand")]
    assert (hand_c.support_rate.k, hand_c.support_rate.n) == (2, 3)  # can't tell leaves the rate
    assert rows[(G, "hand")].support_rate.n == 1


def test_labels_join_through_the_page_key(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "support_label_key.jsonl").write_text(
        '{"id": "s01", "citation_ref": "1:v-001:m:1"}\n', encoding="utf-8"
    )
    (data / "support_labels.jsonl").write_text(
        '{"id": "s01", "label": "supported"}\n{"id": "s99", "label": "supported"}\n',
        encoding="utf-8",
    )
    assert load_hand_labels(tmp_path) == {"1:v-001:m:1": "supported"}


def test_the_gap_runs_from_answer_to_text_fetch(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    rows = {
        "answers.jsonl": [
            {"run": 1, "question_id": "v-001", "model": "m", "answered_at": "2026-11-16T18:00:00Z"}
        ],
        "citations.jsonl": [
            {"run": 1, "question_id": "v-001", "model": "m", "ordinal": 1, "url": "https://e.org/a"}
        ],
        "support_text_fetches.jsonl": [
            {"url": "https://e.org/a", "fetched_at": "2026-11-17T06:00:00Z"}
        ],
        "support_label_key.jsonl": [{"id": "s01", "citation_ref": "1:v-001:m:1"}],
    }
    for name, rs in rows.items():
        (data / name).write_text("".join(json.dumps(r) + "\n" for r in rs), encoding="utf-8")
    assert gaps(tmp_path) == [{"citation_ref": "1:v-001:m:1", "gap_days": 0.5}]


def test_every_labelled_citation_gets_a_gap_or_is_listed_as_missing(tmp_path: Path):
    """SUP-06 (M3.2 pass 1): gaps are written out, and an item with no text fetch is named."""
    test_the_gap_runs_from_answer_to_text_fetch(tmp_path)
    data = tmp_path / "data"
    with (data / "support_label_key.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "s02", "citation_ref": "1:v-002:m:1"}) + "\n")
    out = json.loads(write_gaps(tmp_path).read_text(encoding="utf-8"))
    assert out["gaps"] == [{"citation_ref": "1:v-001:m:1", "gap_days": 0.5}]
    assert out["no_post_fix_text_fetch"] == ["1:v-002:m:1"]
    assert out["median_days"] == out["max_days"] == 0.5


def test_finalise_deletes_the_cache_and_the_store(tmp_path: Path):
    cache = tmp_path / "bodies"
    (cache / "evalkit-store" / "ab").mkdir(parents=True)
    (cache / ".citewatch-body-cache").touch()  # the fetcher marks every cache it creates
    (cache / "page.txt").write_text("text", encoding="utf-8")
    assert finalise(cache) == [] and not cache.exists()
    assert finalise(cache) == []


def test_finalise_refuses_a_path_that_is_not_a_body_cache(tmp_path: Path):
    """Pass 1 L5: a mis-set CITEWATCH_BODY_CACHE must not rmtree an arbitrary folder."""
    other = tmp_path / "projects"
    (other / "keep").mkdir(parents=True)
    problems = finalise(other)
    assert problems and "does not look like a citewatch body cache" in problems[0]
    assert (other / "keep").is_dir()
    named = tmp_path / "work" / "bodies"  # a user folder that merely shares the name
    named.mkdir(parents=True)
    assert finalise(named) and named.is_dir()
    marked = tmp_path / "custom-cache"
    marked.mkdir()
    (marked / ".citewatch-body-cache").write_text("", encoding="utf-8")
    assert finalise(marked) == [] and not marked.exists()


def test_kappa_is_left_out_when_the_owner_labels_are_all_one_value():
    """Pass 1 L4: a constant hand label makes kappa 0 by construction, not a finding."""
    refs = [f"1:v-{i:03d}:claude-sonnet-5-5:1" for i in range(4)]
    verdicts = [
        SupportVerdict(citation_ref=r, judge="j", verdict="supported" if i < 2 else "unsupported")
        for i, r in enumerate(refs)
    ]
    (row,) = [
        r for r in support_rows(verdicts, dict.fromkeys(refs, "supported"), 1) if r.judge == "j"
    ]
    assert row.kappa is None and row.hand_agreement == 0.5
