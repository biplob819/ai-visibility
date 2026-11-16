"""HND-01..03: the held-out hand date check."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

import pytest

from citewatch.handcheck import (
    _allocate,
    accuracy,
    dates_fingerprint,
    draw_hand_sample,
    publish_problems,
    tuning_urls,
    write_once,
)
from citewatch.schemas import HandDateLabel

ROOT = Path(__file__).resolve().parents[2]


def pages(spec: dict[str, int], undated: int = 8, failed: int = 3):
    out = []
    for source, n in spec.items():
        out += [
            {
                "url": f"https://{source}.org/{i}",
                "outcome": "ok",
                "effective_date": "2025-01-01",
                "effective_source": source,
            }
            for i in range(n)
        ]
    out += [
        {"url": f"https://none.org/{i}", "outcome": "ok", "effective_date": None}
        for i in range(undated)
    ]
    out += [
        {"url": f"https://gone.org/{i}", "outcome": "blocked", "effective_date": None}
        for i in range(failed)
    ]
    return out


def test_allocation_is_proportional_with_a_floor_of_five():
    alloc = _allocate(
        {"schema_org": 300, "visible_text": 120, "page_age": 60, "meta_tag": 12, "sitemap": 3}, 50
    )
    assert sum(alloc.values()) == 50
    assert alloc["sitemap"] == 0 and alloc["meta_tag"] >= 5 and alloc["page_age"] >= 5
    assert alloc["schema_org"] > alloc["visible_text"] > alloc["page_age"]


def test_allocation_never_takes_more_than_a_source_has():
    alloc = _allocate({"a": 6, "b": 5}, 50)
    assert alloc == {"a": 6, "b": 5}


def test_fifty_dated_plus_five_undated_seeded_and_held_out():
    ps = pages({"schema_org": 200, "visible_text": 80, "page_age": 30, "meta_tag": 6})
    held = {"https://schema_org.org/0", "https://none.org/0"}
    rows = draw_hand_sample(ps, seed=52, exclude=held)
    assert Counter(r["role"] for r in rows) == {"dated": 50, "undated": 5}
    assert not held & {r["url"] for r in rows}
    assert not any("gone.org" in r["url"] for r in rows)  # only pages the owner can open
    assert rows == draw_hand_sample(list(reversed(ps)), seed=52, exclude=held)
    assert min(Counter(r["stratum"] for r in rows if r["role"] == "dated").values()) >= 5


def test_the_tuning_set_is_excluded():
    urls = tuning_urls(ROOT / "tests" / "fixtures" / "dates")
    assert len(urls) >= 20


def test_the_sample_is_written_once(tmp_path):
    p = write_once(tmp_path / "hand_sample.jsonl", [{"url": "u"}])
    with pytest.raises(FileExistsError):
        write_once(p, [{"url": "u"}])


def test_accuracy_within_seven_days_exact_and_undated():
    d = dt.date
    sample = [
        {"url": "a", "stratum": "schema_org", "role": "dated"},
        {"url": "b", "stratum": "schema_org", "role": "dated"},
        {"url": "c", "stratum": "visible_text", "role": "dated"},
        {"url": "e", "stratum": "visible_text", "role": "dated"},
        {"url": "u", "stratum": "undated", "role": "undated"},
    ]
    labels = {
        "a": HandDateLabel(url="a", true_modified=d(2025, 1, 1), not_determinable=False),
        "b": HandDateLabel(url="b", true_published=d(2025, 1, 9), not_determinable=False),
        "c": HandDateLabel(url="c", true_modified=d(2024, 1, 1), not_determinable=False),
        "e": HandDateLabel(url="e", not_determinable=True),
        "u": HandDateLabel(url="u", not_determinable=True),
    }
    eff = {"a": d(2025, 1, 1), "b": d(2025, 1, 2), "c": d(2025, 1, 1), "e": d(2025, 1, 1)}
    rows = {r.source: r for r in accuracy(sample, labels, eff)}
    assert (rows["overall"].within_7_days.k, rows["overall"].within_7_days.n) == (
        2,
        3,
    )  # e not judged
    assert rows["overall"].exact.k == 1
    assert rows["schema_org"].within_7_days.k == 2 and rows["visible_text"].within_7_days.k == 0
    assert rows["undated"].within_7_days.k == 1


def test_a_resolver_change_after_labelling_blocks_publishing_until_25_fresh_labels(tmp_path):
    pkg = tmp_path / "dates"
    pkg.mkdir()
    (pkg / "rules.py").write_text("A = 1\n", encoding="utf-8")
    v1 = dates_fingerprint(pkg)
    (pkg / "rules.py").write_text("A = 2\n", encoding="utf-8")
    v2 = dates_fingerprint(pkg)
    assert v1 != v2
    assert publish_problems({"version": v1}, current=v1) == []
    assert publish_problems({"version": v1, "labelled_by_version": {v2: 24}}, current=v2)
    assert publish_problems({"version": v1, "labelled_by_version": {v2: 25}}, current=v2) == []
