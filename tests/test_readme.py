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
LIVE = (
    "https://biplob819.github.io/ai-visibility/",
    "https://github.com/biplob819/",
    "https://raw.githubusercontent.com/biplob819/ai-visibility/main/",
)


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


def test_the_readme_rerun_commands_run_offline_as_written(tmp_path: Path):
    """B4.4 pass 1: the documented init / doctor / dry-run steps work with no keys."""
    import subprocess
    import sys

    text = README.read_text("utf-8")
    assert "uv sync --extra anthropic --extra openai" in text
    assert "--contact <a page site owners can reach you at>" in text
    assert "scripts/measure_cost.py my-study --run 0" in text
    exe = [
        sys.executable,
        "-c",
        "import sys; from citewatch.cli import main; sys.exit(main(sys.argv[1:]))",
    ]
    env = {k: v for k, v in __import__("os").environ.items() if not k.endswith("_API_KEY")}

    def run(*args: str) -> int:
        return subprocess.run([*exe, *args], cwd=tmp_path, env=env, capture_output=True).returncode

    assert run("init", "my-study", "--contact", "https://github.com/someone/project") == 0
    assert run("doctor", "--study", "my-study") == 2  # names the missing keys
    assert run("ask", "--run", "0", "--dry-run", "--study", "my-study") == 0
    assert run("report", "--example") == 0


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
    # B4.5 pass 2: PyPI renders the README, so repository links are absolute blob URLs; each
    # must name a file that exists here, and no relative link is left to break on PyPI
    assert not [u for u in links if not u.startswith(("http://", "https://", "#"))]
    blob = "https://github.com/biplob819/ai-visibility/blob/main/"
    local = [u[len(blob) :] for u in links if u.startswith(blob)]
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
    bullets = [
        b
        for b in (ROOT / "docs" / "deviations.md").read_text("utf-8").splitlines()
        if b.startswith("- **")
    ]
    assert bullets
    for b in bullets:  # pass 1: every reported-against-plan item names its decision too
        ids = re.findall(r"D-\d+", b)
        assert ids and set(ids) <= known, b
