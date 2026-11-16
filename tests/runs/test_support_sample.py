"""SUP-01: the seeded, stratified support sample, drawn once."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from citewatch.fetch.pages import main_text
from citewatch.schemas import load_questions, load_study_config
from citewatch.support import draw_sample, read_sample, write_sample

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "studies" / "uk-health"


@pytest.fixture
def cfg_qs():
    cfg = load_study_config(STUDY / "study.yaml")
    return cfg, load_questions(STUDY / "questions.jsonl", cfg)


def fake_citations(qs, models, run=1, per_answer=3):
    out = []
    for q in qs:
        for m in models:
            for o in range(1, per_answer + 1):
                out.append(
                    {
                        "run": run,
                        "question_id": q.id,
                        "model": m,
                        "ordinal": o,
                        "url": f"https://e.org/{q.id}/{m}/{o}",
                        "answer_span": "A claim." if o != 2 else "",
                    }
                )
    return out


def test_fifty_stratified_citations_with_two_reserves_each(cfg_qs):
    cfg, qs = cfg_qs
    rows = draw_sample(fake_citations(qs, cfg.models), cfg, qs)
    sample = [r for r in rows if r["role"] == "sample"]
    assert len(sample) == 50 and len(rows) == 70
    assert Counter(r["model"] for r in sample) == {m: 25 for m in cfg.models}
    assert set(Counter((r["model"], r["intent"]) for r in sample).values()) == {5}
    assert set(
        Counter((r["model"], r["intent"]) for r in rows if r["role"] == "reserve").values()
    ) == {2}
    assert len({r["citation_ref"] for r in rows}) == 70


def test_the_draw_is_seeded_and_skips_empty_claims_and_other_runs(cfg_qs):
    cfg, qs = cfg_qs
    cites = fake_citations(qs, cfg.models) + fake_citations(qs, cfg.models, run=0)
    a, b = draw_sample(cites, cfg, qs), draw_sample(list(reversed(cites)), cfg, qs)
    assert a == b
    assert all(
        r["citation_ref"].startswith("1:") and not r["citation_ref"].endswith(":2") for r in a
    )


def test_the_sample_is_written_once(tmp_path, cfg_qs):
    cfg, qs = cfg_qs
    rows = draw_sample(fake_citations(qs, cfg.models), cfg, qs)
    write_sample(tmp_path, rows)
    assert read_sample(tmp_path) == rows
    with pytest.raises(FileExistsError):
        write_sample(tmp_path, rows)


def test_kept_text_drops_navigation_footers_and_forms():
    html = (
        "<nav>Home Menu</nav><main><p>Drink 6 to 8 glasses a day.</p></main>"
        "<footer>Page last reviewed</footer><form><button>Search</button></form>"
    )
    assert main_text(html) == "Drink 6 to 8 glasses a day."


def test_kept_text_puts_each_block_on_its_own_line():
    """D-61: glued paragraphs broke sentence splitting and the judges' quote check."""
    html = (
        "<p>Eat a healthy diet</p><p>Not all processed food is bad.</p>"
        "<ul><li>One</li><li>Two</li></ul>a<br>b<br/>c"
    )
    assert main_text(html).splitlines() == [
        "Eat a healthy diet",
        "Not all processed food is bad.",
        "One",
        "Two",
        "a",
        "b",
        "c",
    ]
