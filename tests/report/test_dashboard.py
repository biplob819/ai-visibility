"""DSH-01, DSH-02, DSH-04: the findings dashboard (node B4.1)."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from citewatch.cli import main
from citewatch.report import dashboard, render
from citewatch.schemas import StudySummary

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "studies" / "uk-health"


@pytest.fixture(scope="module")
def summary() -> StudySummary:
    return StudySummary.model_validate_json((STUDY / "results" / "summary.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def page(summary: StudySummary) -> str:
    return render(summary, "UK health")


class _Collect(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.urls: list[str] = []
        self.text: list[str] = []
        self.tags: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"] or "")
        for k in ("src", "href", "srcset", "action", "data"):
            if a.get(k):
                self.urls.append(a[k] or "")

    def handle_data(self, data):
        self.text.append(data)


def _parse(page: str) -> _Collect:
    p = _Collect()
    p.feed(page)
    return p


def test_every_summary_field_has_a_rendered_section(page: str):
    """DSH-04: walk the schema, so a new summary field without a section fails here."""
    ids = _parse(page).ids
    for field in StudySummary.model_fields:
        section = dashboard.FIELD_SECTION.get(field, field)
        assert section in ids, field
    assert [k for k, _ in dashboard.SECTIONS] == list(dashboard.RENDER)


def test_the_page_is_self_contained(page: str):
    """DSH-01: no scripts, and nothing fetched from elsewhere (links out are fine)."""
    p = _parse(page)
    assert "script" not in p.tags and "link" not in p.tags and "iframe" not in p.tags
    assert "@import" not in page and "url(" not in page
    fetched = [u for u in p.urls if not u.startswith(("#", "https://github.com/"))]
    assert fetched == []


def test_every_percentage_carries_a_count(page: str):
    """DSH-01 / FR9: every printed percentage is a value with its count, or a bound inside the
    interval that follows one (chart axis ticks, drawn inside the SVG, are not printed text)."""
    body = re.sub(r"<style>.*?</style>|<svg.*?</svg>", " ", page, flags=re.S)
    text = re.sub(r"\s+", " ", " ".join(_parse(body).text))
    text = re.sub(r"\(\d+(?:/\d+|)?(?:n=\d+)?;? ?95% CI [^)]*\)", "(counted)", text)
    text = re.sub(r"\(n=\d+; 95% CI [^)]*\)", "(counted)", text)
    text = re.sub(r"\((\d+/\d+|n=\d+)\)", "(counted)", text)  # a count with no interval
    loose = [
        text[max(0, m.start() - 40) : m.end() + 25]
        for m in re.finditer(r"\d+(?:\.\d+)?%", text)
        if not text[m.end() : m.end() + 10].startswith((" (counted)", " CI", " interval"))
        and not text[max(0, m.start() - 7) : m.start()].endswith("target ")  # a goal, not a value
    ]
    assert loose == []


def test_page_one_has_the_scope_and_both_checks_with_their_method(page: str, summary):
    """DSH-02: sourcing not medical accuracy; directional; coverage, errors, both checks."""
    head = page[: page.index('id="share"')]
    assert "does <strong>not</strong> judge whether any answer or page is medically" in head
    assert "directional" in head and "Date coverage" in head and "Errors:" in head
    assert summary.check_methods["date_accuracy"] in head
    assert summary.check_methods["support_hand"] in head
    for r in summary.support:
        assert f"{r.support_rate.k}/{r.support_rate.n}" in head


def test_headline_numbers_trace_to_the_summary(page: str, summary):
    """Every number in the headline is a summary value, printed with its count."""
    nhs = {
        (r.model, r.run): r.share
        for r in summary.share
        if r.publisher == "nhs.uk" and r.kind == "presence" and r.intent is None
    }
    head = page[page.index('id="headline"') : page.index('id="scope"')]
    for model in ("claude-sonnet-5-5", "gpt-6.1-sol"):
        iv = nhs[(model, 1)]
        assert f"{dashboard.pct(iv.point)} ({iv.k}/{iv.n}" in head
    stale = [r for r in summary.stale if r.intent is None and r.definition == "primary"]
    for r in stale:
        assert f"({r.rate.k}/{r.rate.n};" in head


def test_identity_never_rests_on_colour_alone(page: str):
    """DSH-04: each model has its own marker shape and every marker names its series."""
    assert page.count('class="legend"') >= 3
    shapes = {"circle": "<circle", "square": "<rect", "diamond": "<polygon"}
    assert page.count(shapes["circle"]) > 0 and page.count(shapes["square"]) > 0
    for m in re.finditer(r"<(circle|rect|polygon)[^>]*>(<title>[^<]*</title>)?", page):
        if "chart" in page[max(0, m.start() - 4000) : m.start()]:
            assert m.group(2), m.group(0)


def test_light_and_dark_themes_are_both_defined(page: str):
    assert "prefers-color-scheme:dark" in page and ':root[data-theme="dark"]' in page
    assert "--series-1:#2a78d6" in page and "--series-1:#3987e5" in page


def test_small_cells_are_marked_directional(summary):
    small = (
        next(r for r in summary.stale if r.rate.n < dashboard.DIRECTIONAL_N)
        if any(r.rate.n < dashboard.DIRECTIONAL_N for r in summary.stale)
        else None
    )
    iv = small.rate if small else type(summary.coverage)(point=0.5, lo=0.1, hi=0.9, n=4, k=2)
    assert dashboard.counted(iv).endswith("directional")
    assert not dashboard.counted(summary.coverage).endswith("directional")


def test_report_writes_the_study_dashboard(tmp_path: Path, capsys):
    import shutil

    study = tmp_path / "uk-health"
    (study / "results").mkdir(parents=True)
    shutil.copy(STUDY / "study.yaml", study / "study.yaml")
    shutil.copy(STUDY / "results" / "summary.json", study / "results" / "summary.json")
    assert main(["report", "--study", str(study), "--title", "UK health", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    page = (study / "results" / "site" / "index.html").read_text("utf-8")
    assert out["dashboard"].endswith("index.html") and "What AI search cites for UK health" in page


def test_report_example_needs_no_study_and_no_keys(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert main(["report", "--example"]) == 0
    assert (tmp_path / "citewatch-example" / "index.html").is_file()


def test_report_without_a_summary_exits_2(tmp_path: Path, capsys):
    import shutil

    study = tmp_path / "s"
    study.mkdir()
    shutil.copy(STUDY / "study.yaml", study / "study.yaml")
    assert main(["report", "--study", str(study), "--json"]) == 2
    assert "run `citewatch score` first" in capsys.readouterr().out


def test_the_bundled_example_is_the_flagship_summary():
    import gzip

    blob = ROOT / "src" / "citewatch" / "examples" / "uk-health-summary.json.gz"
    assert gzip.decompress(blob.read_bytes()) == (STUDY / "results" / "summary.json").read_bytes()


def test_the_headline_survives_a_publisher_one_model_never_cited(summary: StudySummary):
    """B4.1 pass 1 M2: the largest separated difference may be a publisher with no row for one
    model; it shows as 0 of that model's answers, never a crash."""
    rows = [r for r in summary.share if not (r.publisher == "nhs.uk" and r.model == "gpt-6.1-sol")]
    s = summary.model_copy(update={"share": tuple(rows)})
    page = render(s, "UK health")
    head = page[page.index('id="headline"') : page.index('id="scope"')]
    assert "0% (0/100" in head


def test_per_intent_stale_rows_are_marked_directional(page: str):
    """H13 (pass 1 M1): every per-intent stale row says directional, whatever its n."""
    table = page[page.index('id="stale"') : page.index('id="freshness"')]
    rows = re.findall(
        r"<tr><th scope='row'>[^<]+</th><td>([^<]+)</td>"
        r"<td>(primary|secondary)</td><td>([^<]+)</td>",
        table,
    )
    assert rows
    for intent, _definition, value in rows:
        assert value.endswith("directional") == (intent != "All intents"), (intent, value)


def test_scope_comes_from_the_summary_and_the_config(summary: StudySummary):
    """Pass 1 M3: nothing about the flagship study is hard-coded."""
    page = render(summary, "Irish health", location="Dublin, IE", word_limit=200)
    scope = page[page.index('id="scope"') : page.index('id="checks"')]
    assert "Irish health questions" in scope and "from Dublin, IE" in scope
    assert "100 pre-registered questions across 5 intents, asked twice" in scope
    assert "over the 200-word limit" in page
    assert "London" not in render(summary, "X")


def test_comparison_columns_hold_what_their_headers_say(page: str):
    table = page[page.index('id="comparisons"') : page.index('id="concentration"')]
    assert (
        "<th scope='col'>Models compared</th><th scope='col'>Difference in presence share</th>"
        in table
    )
    first = re.search(
        r"<tr><th scope='row'>run 1</th><td>[^<]+</td><td>([^<]+)</td><td>([^<]+)</td>", table
    )
    assert first and "−" in first.group(1) and "pts" in first.group(2)
