"""CRD-01..03, IMP-01..02: domain cards, lookup and the improvement report (node D5.1).

The tiny study's cards are worked out by hand from tests/metrics/conftest.py; the flagship
study's cards are checked against its summary.json and page_meta.jsonl.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from citewatch import cards as cards_module
from citewatch.cards import NotCited, build_cards, cited_instead, lookup, normalise, read_cards
from citewatch.extract import urls as urls_module
from citewatch.metrics import build_summary
from citewatch.metrics.data import load
from citewatch.schemas import StudySummary, load_questions, load_study_config

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "studies" / "uk-health"
A, B = "claude-sonnet-5-5", "gpt-6.1-sol"
MEDICAL_CLAIMS = re.compile(
    r"\b(accura|inaccura|correct|incorrect|wrong|misinform|unsafe|safe advice|medically|"
    r"clinical(ly)? (valid|sound)|harmful)",
    re.I,
)


def _tiny_cards(tiny: Path):
    cfg = load_study_config(tiny / "study.yaml")
    qs = load_questions(tiny / "questions.jsonl", cfg)
    summary = build_summary(tiny, cfg, qs, resamples=200)
    data = load(tiny, cfg, qs, list(summary.runs))
    return build_cards(tiny, data, summary, cfg.stale_days), summary, data


def test_tiny_cards_count_citations_answers_and_questions(tiny: Path):
    cards, _, _ = _tiny_cards(tiny)
    assert [(c.publisher, c.citations, c.answers_citing) for c in cards] == [
        ("nhs.uk", 7, 7),
        ("bbc.co.uk", 4, 4),
        ("x.com", 3, 2),
    ]
    assert cards[0].questions_citing == ("t-001", "t-002", "t-003")


def test_every_card_share_is_the_summary_row(tiny: Path):
    cards, summary, _ = _tiny_cards(tiny)
    rows = {
        (r.publisher, r.model, r.intent, r.run): r.share
        for r in summary.share
        if r.kind == "presence"
    }
    for card in cards:
        for key, share in card.share_by_model.items():
            model, run = key.split("/")
            assert share == rows[(card.publisher, model, None, int(run.removeprefix("run-")))]
        for key, share in card.share_by_intent.items():
            intent, model, run = key.split("/")
            assert share == rows[(card.publisher, model, intent, int(run.removeprefix("run-")))]
    assert cards[0].share_by_model[f"{A}/run-1"].k == 2


def test_cited_instead_ranks_who_answered_without_the_publisher(tiny: Path):
    """§9 by hand: nhs.uk is missing from t-002 (bbc, x) and t-003 on GPT (bbc twice)."""
    cards, _, data = _tiny_cards(tiny)
    by = {c.publisher: c for c in cards}
    assert by["nhs.uk"].cited_instead == ("bbc.co.uk", "x.com")
    assert by["x.com"].cited_instead == ("bbc.co.uk",)
    assert cited_instead(data, "nobody.org") == ()
    assert all(c.publisher not in c.cited_instead for c in cards)


def test_improvement_rows_by_hand(tiny: Path):
    """nhs.uk/b (2024-01-01) and nhs.uk/c (2025-11-01) are over 365 days before the
    2026-11-20 answers; x.com's two pages loaded with no date; bbc's page is newer."""
    cards, _, _ = _tiny_cards(tiny)
    by = {c.publisher: {i.code: i for i in c.improvement} for c in cards}
    stale = by["nhs.uk"]["stale"]
    assert (stale.count, stale.of, stale.source) == (2, 3, "page_meta.jsonl")
    assert stale.examples == ("https://nhs.uk/b", "https://nhs.uk/c")
    undated = by["x.com"]["undated"]
    assert (undated.count, undated.of) == (2, 2)
    assert by["bbc.co.uk"] == {}
    assert "intent_absent" not in by["nhs.uk"]  # cited on both intents


def test_page_outcomes_and_hidden_dates_become_rows(tiny: Path):
    meta = tiny / "data" / "page_meta.jsonl"
    rows = [json.loads(x) for x in meta.read_text("utf-8").splitlines()]
    for r in rows:
        if r["url"] == "https://nhs.uk/a":
            r["effective_source"] = "sitemap"
        if r["url"] == "https://x.com/b":
            r["outcome"] = "robots_disallowed"
        if r["url"] == "https://bbc.co.uk/a":
            r.update(outcome="fetch_error", effective_date=None)
    meta.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    cards, _, _ = _tiny_cards(tiny)
    by = {c.publisher: {i.code: i for i in c.improvement} for c in cards}
    assert (by["nhs.uk"]["hidden_date"].count, by["nhs.uk"]["hidden_date"].of) == (1, 3)
    assert (by["x.com"]["robots_blocked"].count, by["x.com"]["robots_blocked"].of) == (1, 2)
    assert (by["x.com"]["undated"].count, by["x.com"]["undated"].of) == (1, 1)
    assert (by["bbc.co.uk"]["fetch_error"].count, by["bbc.co.uk"]["fetch_error"].of) == (1, 1)


def test_lookup_normalises_input_through_the_extractors_publisher_of(tiny: Path):
    cards, _, _ = _tiny_cards(tiny)
    for q in ("https://www.NHS.uk/conditions/flu?x=1", "nhs.uk", "http://nhs.uk:8080/", "NHS.UK."):
        hit = lookup(q, cards, answers=15)
        assert not isinstance(hit, NotCited) and hit.publisher == "nhs.uk", q
    assert normalise("https://user@www.Example.org:443/a/b?c") == "example.org"
    assert vars(cards_module)["publisher_of"] is urls_module.publisher_of  # one function


def test_lookup_of_an_uncited_publisher_names_the_study_and_the_intents_leaders(tiny: Path):
    cards, _, _ = _tiny_cards(tiny)
    miss = lookup("https://example.org/page", cards, answers=15, intent="beta")
    assert isinstance(miss, NotCited)
    assert miss.message == "example.org was not cited in any of the 15 answers in this study."
    assert miss.top_for_intent == ("bbc.co.uk", "nhs.uk")
    assert isinstance(lookup("", cards, answers=15), NotCited)


def test_flagship_cards_match_the_summary_and_reproduce_on_a_rerun(tmp_path: Path):
    cfg = load_study_config(STUDY / "study.yaml")
    qs = load_questions(STUDY / cfg.questions_path, cfg)
    summary = StudySummary.model_validate_json(
        (STUDY / "results" / "summary.json").read_text("utf-8")
    )
    cards = build_cards(STUDY, load(STUDY, cfg, qs, list(summary.runs)), summary, cfg.stale_days)
    committed = read_cards(STUDY / "results" / "domain_cards.json")
    assert cards == committed
    cited = {
        json.loads(x)["publisher"]
        for x in (STUDY / "data" / "citations.jsonl").read_text("utf-8").splitlines()
        if x.strip() and json.loads(x)["run"] in summary.runs
    }
    assert {c.publisher for c in cards} == cited


def test_flagship_page_counts_reproduce_from_page_meta():
    cards = read_cards(STUDY / "results" / "domain_cards.json")
    meta = {
        r["url"]: r
        for r in (
            json.loads(x)
            for x in (STUDY / "data" / "page_meta.jsonl").read_text("utf-8").splitlines()
        )
    }
    runs = {1, 2}
    urls: dict[str, set[str]] = {}
    for x in (STUDY / "data" / "citations.jsonl").read_text("utf-8").splitlines():
        c = json.loads(x)
        if c["run"] in runs:
            urls.setdefault(c["publisher"], set()).add(c["url"])
    for card in cards:
        rows = {i.code: i for i in card.improvement}
        mine = urls[card.publisher]
        blocked = sum(meta[u]["outcome"] == "robots_disallowed" for u in mine if u in meta)
        assert rows.get("robots_blocked") is None or rows["robots_blocked"].count == blocked
        if blocked:
            assert rows["robots_blocked"].of == len(mine)


def test_every_finding_has_a_fix_and_evidence_and_no_medical_claim():
    cards = read_cards(STUDY / "results" / "domain_cards.json")
    rows = [i for c in cards for i in c.improvement]
    assert rows
    for i in rows:
        assert i.fix and 0 < i.count <= i.of and i.source
        assert not MEDICAL_CLAIMS.search(i.finding + " " + i.fix), (i.code, i.finding, i.fix)


def test_lookup_on_the_flagship_cards_is_fast():
    cards = read_cards(STUDY / "results" / "domain_cards.json")
    start = time.perf_counter()
    for q in ("nhs.uk", "https://www.bbc.co.uk/news", "nobody.example", "nice.org.uk"):
        lookup(q, cards, answers=400, intent="treatment")
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize("bad", ["", "   ", "://", "http://"])
def test_lookup_never_raises_on_junk(tiny: Path, bad: str):
    cards, _, _ = _tiny_cards(tiny)
    assert isinstance(lookup(bad, cards, answers=15), NotCited)
