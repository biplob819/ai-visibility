"""PST-01..03: the write-up (node B4.2)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from citewatch.cards import read_cards
from citewatch.report import dashboard
from citewatch.report.post import SIGNAL_SPEC, render
from citewatch.schemas import Interval, StudySummary

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "studies" / "uk-health"
CHECKLIST = ROOT / "docs" / "post-review-b9.md"


@pytest.fixture(scope="module")
def summary() -> StudySummary:
    return StudySummary.model_validate_json((STUDY / "results" / "summary.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def page(summary: StudySummary) -> str:
    return render(summary, read_cards(STUDY / "results" / "domain_cards.json"), "UK health")


def _text(page: str) -> str:
    body = re.sub(r"<style>.*?</style>|<svg.*?</svg>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def _printed(s: StudySummary) -> set[str]:
    out: set[str] = set()

    def walk(x) -> None:
        if isinstance(x, Interval):
            out.add(dashboard.counted(x))
            out.add(dashboard.counted(x, directional=True))
        elif hasattr(type(x), "model_fields"):
            for f in type(x).model_fields:
                walk(getattr(x, f))
        elif isinstance(x, (list, tuple)):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)

    walk(s)
    return out


def test_it_opens_with_the_main_finding_then_the_scope(page: str):
    """PST-01: the lede is the finding; the scope statement follows before any section."""
    first_h2 = page.index("<h2>")
    lede, scope = page.index("class='lede'"), page.index("class='scope'")
    assert lede < scope < first_h2
    head = page[:first_h2]
    assert "nhs.uk" in head and "83% (83/100" in head
    assert "medically accurate" in head and "directional" in head


def test_it_links_the_signal_spec_and_the_dashboard(page: str):
    assert f'href="{SIGNAL_SPEC}"' in page
    assert 'href="../"' in page
    assert (ROOT / "docs" / "signal-spec.pdf").is_file()


def test_every_value_in_the_post_traces_to_the_summary(page: str, summary: StudySummary):
    """PST-02: printed values with counts are summary Intervals; bare numbers are summary or
    card counts."""
    text = _text(page)
    known = _printed(summary)
    values = re.findall(r"\d+(?:\.\d+)?% \([^)]*\)(?: · directional)?", text)
    assert len(values) >= 20
    zeros = {f"0% (0/{n}; 95% CI 0%–0%)" for n in dashboard._answers(summary).values()}
    assert [v for v in values if v not in known and v not in zeros] == []
    cards = read_cards(STUDY / "results" / "domain_cards.json")
    assert f"each of the {len(cards)} cited publishers" in text
    assert f"${summary.spend_usd:.2f}" in text
    answers = sum(
        v["answers"] for k, v in summary.error_counts.items() if k.startswith(("claude", "gpt"))
    )
    assert f"{answers} answers in all" in text
    # bare counts (pass 1, M1): improvement-code publisher counts, comparisons, held-out labels
    from collections import Counter

    codes = Counter(i.code for c in cards for i in c.improvement)
    for code, n in codes.most_common(3):
        assert f"({n} publishers)" in text, code
    sep = sum(c.separated for c in summary.comparisons)
    assert f"{sep} of {len(summary.comparisons)} paired comparisons" in text
    assert f"On {summary.error_counts['hand_dates']['labels']} held-out pages" in text
    hidden = [
        r.within_7_days
        for r in summary.date_accuracy
        if r.source in ("sitemap", "http_header", "page_age")
    ]
    assert f"on {sum(iv.k or 0 for iv in hidden)} of {sum(iv.n for iv in hidden)} pages" in text
    cells = sorted({r.rate.n // len(summary.runs) for r in summary.stale if r.intent})
    assert f"rest on {cells[0]} to {cells[-1]} questions" in text


def test_the_charts_are_drawn_from_the_summary(page: str):
    assert page.count('<svg class="chart"') == 3
    for caption in ("presence share", "Primary definition", "Cross-model overlap"):
        assert caption in page


def test_the_support_paragraph_discloses_the_pace_and_does_not_settle_the_rate(page: str):
    """OWNER D-62 (pass 1, H1): the owner's labels sit beside the judges with their pace, and
    the post does not claim where the true rate lies."""
    text = _text(page)
    assert "one to two seconds per citation" in text
    assert "this check cannot settle the true rate" in text
    assert "somewhere between" not in text
    assert "agent-checked, owner-approved" in text


def test_the_post_never_advises_gaming_ai_answers(page: str):
    """B9 (mechanical part): no optimisation advice vocabulary in the text."""
    text = _text(page).lower()
    for phrase in (
        "optimi",
        "rank higher",
        "get cited more",
        "boost",
        "keyword",
        "llms.txt",
        "geo ",
    ):
        assert phrase not in text, phrase
    assert "not, and will not be, advice on gaming ai answers" in text


def test_the_b9_checklist_is_committed_and_signed_off():
    """PST-03: every item answered and the owner's sign-off recorded."""
    text = CHECKLIST.read_text("utf-8")
    rows = [r for r in text.splitlines() if re.match(r"\| \d+ \|", r)]
    assert len(rows) == 8
    answers = [[c.strip() for c in r.strip().strip("|").split("|")][2] for r in rows]
    assert all(a.lower().startswith("yes") for a in answers), answers
    m = re.search(r"Reviewed by: (.+?)  Date: (.+?)  Decision: (.+)$", text, re.M)
    assert m and "_" not in m.group(1) and "_" not in m.group(2)
    assert m.group(3).strip() == "approve"
