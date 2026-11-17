"""REL-01, REL-03: the README's finding, links and the deviations record."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from citewatch.report.dashboard import counted
from citewatch.schemas import Interval, StudySummary

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SUMMARY = ROOT / "studies" / "uk-health" / "results" / "summary.json"
LIVE = ("https://biplob819.github.io/ai-visibility/", "https://github.com/biplob819/")


def _intervals(s: StudySummary) -> set[str]:
    out: set[str] = set()

    def walk(x) -> None:
        if isinstance(x, Interval):
            out.add(counted(x))
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


def test_every_value_in_the_readme_is_a_summary_interval():
    """REL-01: the finding's numbers are the study's, printed with counts and intervals."""
    text = README.read_text("utf-8")
    s = StudySummary.model_validate_json(SUMMARY.read_text("utf-8"))
    values = re.findall(r"\d+(?:\.\d+)?% \([^)]*95% CI [^)]*\)", text)
    assert len(values) >= 9  # six in the table, overlap, coverage and the date check
    assert [v for v in values if v not in _intervals(s)] == []
    assert f"${s.spend_usd:.2f}" in text


def test_the_readme_covers_finding_method_rerun_cost_licence_and_data_card():
    text = README.read_text("utf-8")
    for heading in (
        "## What the first study found",
        "## How it works",
        "## Rerun it",
        "## Licence",
    ):
        assert heading in text
    for needle in ("**Cost.**", "DATA_CARD.md", "LICENSE", "sourcing, not medical accuracy"):
        assert needle in text


def test_every_local_link_in_the_readme_resolves():
    text = README.read_text("utf-8")
    links = re.findall(r"\]\(([^)]+)\)", text)
    local = [u for u in links if not u.startswith(("http://", "https://", "#"))]
    assert local
    missing = [u for u in local if not (ROOT / unquote(u.split("#")[0])).exists()]
    assert missing == []
    remote = [u for u in links if u.startswith("http")]
    assert all(u.startswith(LIVE) for u in remote), remote


def test_the_decisions_preregistration_and_deviations_are_published_and_linked():
    """REL-03: every deviation names a decision that exists."""
    text = README.read_text("utf-8")
    for path in ("docs/decisions.md", "docs/preregistration.md", "docs/deviations.md"):
        assert path in text and (ROOT / path).is_file()
    decisions = (ROOT / "docs" / "decisions.md").read_text("utf-8")
    known = set(re.findall(r"^\| (?:OWNER )?(D-\d+) \|", decisions, re.M))
    rows = [
        r
        for r in (ROOT / "docs" / "deviations.md").read_text("utf-8").splitlines()
        if r.startswith("| ") and "---" not in r and not r.startswith("| Decision")
    ]
    assert len(rows) >= 8
    for row in rows:
        ids = re.findall(r"D-\d+", row.split("|")[1])
        assert ids and set(ids) <= known, row
