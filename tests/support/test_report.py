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


def test_finalise_deletes_the_cache_and_the_store(tmp_path: Path):
    cache = tmp_path / "bodies"
    (cache / "evalkit-store" / "ab").mkdir(parents=True)
    (cache / "page.txt").write_text("text", encoding="utf-8")
    assert finalise(cache) == [] and not cache.exists()
    assert finalise(cache) == []
