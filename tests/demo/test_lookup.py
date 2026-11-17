"""DEM-01: lookup by default over the bundled domain cards, and a top-ten picker by intent. It
reads the cards only and never calls a model."""

from __future__ import annotations

import ast
import json
import logging
import re
import time
from pathlib import Path

import pytest

from citewatch.cards import NotCited
from citewatch.demo.lookup import (
    Bundle,
    card_html,
    find,
    load_bundle,
    not_cited_html,
    top_ten,
)
from citewatch.demo.markup import text
from citewatch.schemas import DomainCard
from harness_lib import ROOT

STUDY = ROOT / "studies" / "uk-health"
CARDS = STUDY / "results" / "domain_cards.json"


@pytest.fixture(scope="module")
def bundle() -> Bundle:
    return load_bundle(CARDS)


def test_bundle_counts_the_scored_answers_and_intents(bundle):
    # 100 questions x 2 models x 2 scored runs; the answer count the not-cited line names
    assert bundle.answers == 400
    assert bundle.intents == ("fitness", "nhs_services", "nutrition", "symptoms", "treatment")


@pytest.mark.parametrize("query", ["nhs.uk", "https://www.nhs.uk/conditions/flu/", "NHS.UK:443"])
def test_lookup_finds_a_cited_publisher(bundle, query):
    card = find(bundle, query)
    assert isinstance(card, DomainCard) and card.publisher == "nhs.uk"


def test_card_shows_shares_by_model_cited_instead_and_fixes(bundle):
    card = find(bundle, "nhs.uk")
    assert isinstance(card, DomainCard)
    html = card_html(card)
    for key, share in card.share_by_model.items():
        model = key.split("/")[0]
        assert model in html and f"{share.k} of {share.n} answers" in html
    assert "Cited instead" in html
    for p in card.cited_instead:
        assert p in html
    assert card.improvement
    for row in card.improvement:
        assert text(row.finding) in html and text(row.fix) in html
    assert f"median {card.median_freshness_lag_days:.0f} days" in html


def test_not_cited_names_the_answers_and_top_publishers_for_the_intent(bundle):
    miss = find(bundle, "never-cited-example.org", "fitness")
    assert isinstance(miss, NotCited)
    assert miss.message == (
        "never-cited-example.org was not cited in any of the 400 answers in this study."
    )
    top = [r.publisher for r in top_ten(bundle, "fitness")]
    assert list(miss.top_for_intent) == top[: len(miss.top_for_intent)]
    html = not_cited_html(miss, "fitness")
    assert "on fitness questions" in html
    assert all(p in html for p in miss.top_for_intent)


def test_not_a_web_address(bundle):
    miss = find(bundle, "what is <b>this</b>")
    assert isinstance(miss, NotCited) and miss.publisher is None
    assert "<b>" not in not_cited_html(miss, None)


def test_top_ten_by_intent_ranks_by_answers_citing(bundle):
    for intent in (None, *bundle.intents):
        rows = top_ten(bundle, intent)
        assert len(rows) == 10
        assert [r.rank for r in rows] == list(range(1, 11))
        counts = [r.answers_citing for r in rows]
        assert counts == sorted(counts, reverse=True)
        assert all(0 < r.share <= 1 for r in rows)
    # worked from the cards themselves: the leader's pooled k over the intent's keys
    leader = top_ten(bundle, "nhs_services")[0]
    card = next(c for c in bundle.cards if c.publisher == leader.publisher)
    k = sum(s.k or 0 for key, s in card.share_by_intent.items() if key.startswith("nhs_services/"))
    assert leader.answers_citing == k
    assert top_ten(bundle, "nhs_services")[0].answers == 80  # 20 questions x 2 models x 2 runs


def test_top_ten_rejects_an_unknown_intent(bundle):
    with pytest.raises(ValueError, match="unknown intent"):
        top_ten(bundle, "astrology")


def test_lookup_is_fast(bundle):
    t0 = time.perf_counter()
    for q in ("nhs.uk", "bbc.co.uk", "nowhere-example.org"):
        find(bundle, q, "symptoms")
    assert time.perf_counter() - t0 < 1.0  # Tech Spec §9: under a second


def test_card_html_escapes_card_text():
    card = DomainCard(
        publisher="x<script>.example",
        share_by_model={},
        share_by_intent={},
        citations=1,
        answers_citing=1,
        dated_pages=0,
    )
    assert "<script>" not in card_html(card)


INJECTED = "text\n\n![x](https://evil/b.png) and [t](https://evil) :red[loud]"


@pytest.mark.safety
def test_card_text_cannot_inject_markdown(bundle):
    """Every card field the page shows is one line with markdown syntax neutralised, so a
    blank line cannot end the HTML block and let an image or a link render."""
    markdown_it = pytest.importorskip("markdown_it")
    card = find(bundle, "nhs.uk")
    assert isinstance(card, DomainCard) and card.improvement
    row = card.improvement[0].model_copy(
        update={
            "finding": INJECTED,
            "fix": INJECTED,
            "examples": ("https://ok.example/a\n\n![i](https://evil/i.png)", INJECTED),
        }
    )
    evil = card.model_copy(
        update={"publisher": INJECTED, "cited_instead": (INJECTED,), "improvement": (row,)}
    )
    miss = NotCited(INJECTED, None, 400, INJECTED, (INJECTED,))
    md = markdown_it.MarkdownIt("commonmark", {"html": True})
    for html in (card_html(evil), not_cited_html(miss, "sym\n\n[i](https://evil)")):
        assert "\n" not in html
        rendered = md.render(html)
        assert "<img" not in rendered
        assert 'href="https://evil' not in rendered and "href='https://evil" not in rendered


@pytest.mark.safety
def test_no_card_contains_answer_prose(bundle):
    """The cards carry shares, dates, publishers and fixes; never the answers' text (D-17)."""
    html = "".join(card_html(c) for c in bundle.cards)
    sentences = set()
    for line in (STUDY / "data" / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        text = json.loads(line).get("answer_text") or ""
        sentences.update(s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s) >= 60)
    assert len(sentences) > 500
    assert not [s for s in sentences if s in html]


@pytest.mark.safety
def test_lookup_module_imports_no_model_client():
    src = Path(__file__).resolve().parents[2] / "src" / "citewatch" / "demo" / "lookup.py"
    names = set()
    for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    assert not {n for n in names if n.startswith(("citewatch.runners", "anthropic", "openai"))}
    assert not {n for n in names if n.startswith("citewatch.demo.live")}


# --- the page -------------------------------------------------------------------------------------


@pytest.fixture
def no_model_calls(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("lookup mode must never construct a model runner")

    monkeypatch.setattr("citewatch.runners.anthropic_runner.AnthropicRunner.__init__", refuse)
    monkeypatch.setattr("citewatch.runners.openai_runner.OpenAIRunner.__init__", refuse)
    monkeypatch.setattr("citewatch.demo.live.make_runners", refuse)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_page_opens_on_lookup_and_renders_a_card_without_calling_a_model(no_model_calls):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "demo" / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert at.tabs[0].label == "Look up a site"
    at.text_input[0].input("https://www.nhs.uk/conditions/").run()
    assert not at.exception
    cards = [m.value for m in at.markdown if "cw-card" in m.value and "<h3>" in m.value]
    assert cards and "<h3>nhs.uk</h3>" in cards[0]
    at.text_input[0].input("never-cited-example.org").run()
    assert any("was not cited in any of the 400 answers" in m.value for m in at.markdown)
    assert at.dataframe  # the top-ten tab's table
    assert any("not configured" in i.value for i in at.info)  # no secrets: live mode off


def test_page_logs_each_distinct_lookup_once_per_session(no_model_calls, caplog):
    """Any widget change reruns the page; a lookup is logged once per distinct query and
    topic in a session, not once per rerun."""
    from streamlit.testing.v1 import AppTest

    caplog.set_level(logging.INFO, logger="citewatch.demo")

    def lookups() -> int:
        return sum('"mode": "lookup"' in r.getMessage() for r in caplog.records)

    at = AppTest.from_file(str(ROOT / "demo" / "app.py"), default_timeout=120)
    at.run()
    at.text_input[0].input("nhs.uk").run()
    at.run()
    at.run()
    assert lookups() == 1
    at.text_input[0].input("  NHS.UK ").run()  # the same query, typed differently
    assert lookups() == 1
    at.selectbox[0].set_value(at.selectbox[0].options[-1]).run()  # another topic
    assert lookups() == 2
    at.text_input[0].input("bbc.co.uk").run()
    at.run()
    assert lookups() == 3
    assert "nhs" not in caplog.text and "bbc" not in caplog.text
