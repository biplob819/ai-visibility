"""SIG-01, SIG-02: the one-page signal spec (node B4.3)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from citewatch.report.dashboard import counted
from citewatch.schemas import Interval, StudySummary

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "docs" / "signal-spec.pdf"
HTML = ROOT / "docs" / "signal-spec.html"
CHECKLIST = ROOT / "docs" / "signal-spec-checklist.md"
SUMMARY = ROOT / "studies" / "uk-health" / "results" / "summary.json"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_signal_spec", ROOT / "scripts" / "build_signal_spec.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _intervals(s: StudySummary) -> set[str]:
    """Every Interval in the summary, printed the way the page prints values."""
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


def test_the_pdf_is_exactly_one_page():
    data = PDF.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page(?!s)", data)) == 1


def test_the_html_is_rebuilt_from_the_committed_summary():
    """The committed page is what the script makes from the committed summary (no drift)."""
    s = StudySummary.model_validate_json(SUMMARY.read_text("utf-8"))
    assert _builder().render(s) == HTML.read_text("utf-8")


def test_every_quoted_finding_traces_to_the_summary():
    s = StudySummary.model_validate_json(SUMMARY.read_text("utf-8"))
    body = re.sub(r"<style>.*?</style>", " ", HTML.read_text("utf-8"), flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    quoted = re.findall(r"\d+(?:\.\d+)?% \([^)]*95% CI [^)]*\)", text)
    assert len(quoted) >= 9  # four findings (8 values) plus coverage and the date check
    known = _intervals(s)
    assert [q for q in quoted if q not in known] == []
    loose = [
        m.group(0)
        for m in re.finditer(r"\d+(?:\.\d+)?%", text)
        if not any(m.group(0) in q for q in quoted) and "95%" not in m.group(0)
    ]
    assert loose == []
    assert f"${s.spend_usd:.2f}" in text


def test_the_checklist_items_are_on_the_page():
    """SIG-01: buyer, unit of value, delivery, pricing logic, fields, evidence, limits."""
    html = HTML.read_text("utf-8")
    rows = [
        line
        for line in CHECKLIST.read_text("utf-8").splitlines()
        if line.startswith("| ") and "---" not in line
    ][1:]
    assert len(rows) == 7
    for row in rows:
        heading = row.rstrip(" |").rsplit("|", 1)[-1].strip()
        assert heading.lower() in html.lower(), heading
    for needle in ("Unit of value", "Publishers", "AI labs", "No price points"):
        assert needle in html
    assert not re.search(r"[£$€]\s?\d+\s*(?:/|per)\s*(?:month|year|run)", html, re.I)
