"""D5.3: the project page's sources (PRJ-01..03). The portfolio-site session builds the page
from `portfolio.yml` and `docs/case-study.md`; these tests pin the links, every figure against
`summary.json`, the walkthrough GIF's format (OWNER D-86) and the supporting notes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SUMMARY = json.loads(
    (ROOT / "studies" / "uk-health" / "results" / "summary.json").read_text(encoding="utf-8")
)
CASE = (DOCS / "case-study.md").read_text(encoding="utf-8")
META = yaml.safe_load((ROOT / "portfolio.yml").read_text(encoding="utf-8"))

DASHBOARD = "https://biplob819.github.io/ai-visibility/"
POST = "https://biplob819.github.io/ai-visibility/post/"
SPEC = "https://github.com/biplob819/ai-visibility/blob/main/docs/signal-spec.pdf"
REPO = "https://github.com/biplob819/ai-visibility"
DEMO = "https://citewatch.streamlit.app"


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _share(model: str) -> dict:
    (row,) = [
        r
        for r in SUMMARY["share"]
        if r["kind"] == "presence"
        and r["publisher"] == "nhs.uk"
        and r["model"] == model
        and r["run"] == 1
        and r["intent"] is None
    ]
    return row["share"]


def _stale(model: str) -> dict:
    (row,) = [
        r
        for r in SUMMARY["stale"]
        if r["definition"] == "primary" and r["intent"] is None and r["model"] == model
    ]
    return row["rate"]


def _figures() -> dict[str, str]:
    """Each figure the case study states, computed from summary.json."""
    (overlap,) = [
        o
        for o in SUMMARY["overlap"]
        if o["kind"] == "cross_model" and o["run"] == 1 and o["intent"] is None
    ]
    undated = SUMMARY["error_counts"]["undated_pages"]
    unreadable = undated["blocked"] + undated["fetch_error"] + undated["robots_disallowed"]
    return {
        "gpt_nhs": _pct(_share("gpt-6.1-sol")["point"]),
        "claude_nhs": _pct(_share("claude-sonnet-5-5")["point"]),
        "overlap": _pct(overlap["value"]["point"]),
        "gpt_stale": _pct(_stale("gpt-6.1-sol")["point"]),
        "claude_stale": _pct(_stale("claude-sonnet-5-5")["point"]),
        "cost": f"${SUMMARY['spend_usd']:.2f}",
        "undated": f"{sum(undated.values())} of {SUMMARY['coverage']['n']}",
        "unreadable": f"{unreadable} of them",
    }


def test_the_case_study_follows_the_template_and_links_every_artefact():
    for heading in ("## My role", "## Key decisions", "**Links:**"):
        assert heading in CASE
    narrative = CASE.split("## My role")[0].split("\n", 1)[1]
    assert len(narrative.split()) <= 200  # the short narrative the template asks for
    assert len(CASE.split()) < 1200
    links = set(re.findall(r"\]\((https?://[^)]+)\)", CASE))
    assert {DASHBOARD, POST, SPEC, REPO, DEMO} <= links
    assert "deploying" not in CASE


def test_every_figure_in_the_case_study_comes_from_the_summary():
    f = _figures()
    assert (
        f"GPT cited nhs.uk in {f['gpt_nhs']} of\nrun-1 answers, Claude in {f['claude_nhs']}" in CASE
    )
    assert f"overlapped by only {f['overlap']} per question" in CASE
    assert f"{f['gpt_stale']}\nof GPT's time-sensitive answers" in CASE
    assert f"against {f['claude_stale']} of\nClaude's" in CASE
    assert f"cost {f['cost']} in API calls" in CASE
    assert f"{f['undated']}\n   cited URLs ended up with no usable date, {f['unreadable']}" in CASE
    stated = re.findall(r"\b\d+%|\$\d+\.\d\d", CASE)
    allowed = {f[k] for k in ("gpt_nhs", "claude_nhs", "overlap", "gpt_stale", "claude_stale")}
    assert set(stated) <= allowed | {f["cost"], "95%"}, stated


def test_portfolio_metadata_points_at_the_case_study_with_the_same_links():
    """The manifest follows the site's `portfolio add` schema (its templates/portfolio.yml):
    required fields, allowed values and link keys, images as a list with alt text."""
    assert META["case_study"] == "docs/case-study.md" and META["slug"] == "ai-visibility"
    for k in ("title", "tagline", "kind", "status", "year"):
        assert META.get(k), k
    assert META["kind"] in {"product", "open-source", "case-study", "prototype"}
    assert META["status"] in {"live", "launching", "shipped", "building", "design"}
    assert len(META["tagline"]) <= 200
    keys = {"repo", "site", "demo", "report", "package", "video", "prd", "prdOnePage"}
    keys |= {"techspec", "howBuilt", "architecture", "dataflow", "methodology"}
    links = META["links"]
    assert set(links) <= keys and all(v.startswith("https://") for v in links.values())
    assert (links["repo"], links["report"], links["demo"]) == (REPO, DASHBOARD, DEMO)
    assert links["package"] == "https://pypi.org/project/citewatch/"
    proofs = {p["url"] for p in META["proof"]}
    assert {POST, SPEC} <= proofs
    assert isinstance(META["images"], list)
    for im in META["images"]:
        assert im["alt"] and (ROOT / im["src"]).is_file(), im["src"]
    kinds = {im["kind"] for im in META["images"]}
    assert {"walkthrough", "architecture", "dataflow", "screenshot"} <= kinds
    assert "Cloudflare" not in json.dumps(META)  # OWNER D-70: GitHub Pages


def _gif_frames(data: bytes) -> tuple[int, int, list[int], bool]:
    """Width, frame count, per-frame delays (1/100 s) and whether it loops, from the GIF
    blocks (no image library needed)."""
    assert data[:6] in (b"GIF89a", b"GIF87a")
    width = int.from_bytes(data[6:8], "little")
    flags = data[10]
    i = 13 + (3 * 2 ** ((flags & 7) + 1) if flags & 0x80 else 0)
    delays: list[int] = []
    frames, loops = 0, False
    while i < len(data):
        b = data[i]
        if b == 0x3B:  # trailer
            break
        if b == 0x21:  # extension
            label = data[i + 1]
            j = i + 2
            if label == 0xF9:
                delays.append(int.from_bytes(data[j + 2 : j + 4], "little"))
            if label == 0xFF and data[j + 1 : j + 12] == b"NETSCAPE2.0":
                loops = True
            while data[j]:
                j += data[j] + 1
            i = j + 1
        elif b == 0x2C:  # image
            frames += 1
            lflags = data[i + 9]
            j = i + 10 + (3 * 2 ** ((lflags & 7) + 1) if lflags & 0x80 else 0) + 1
            while data[j]:
                j += data[j] + 1
            i = j + 1
        else:
            raise AssertionError(f"bad GIF block {b:#x} at {i}")
    return width, frames, delays, loops


def test_the_walkthrough_gif_is_the_specified_loop_and_is_shown():
    gif = DOCS / "assets" / "walkthrough.gif"
    data = gif.read_bytes()
    assert len(data) < 3_000_000
    width, frames, delays, loops = _gif_frames(data)
    assert width == 960 and loops
    seconds = sum(delays) / 100
    shots = re.findall(r"^\| (\d+) \|", (DOCS / "walkthrough.md").read_text("utf-8"), re.M)
    assert 6 <= len(shots) <= 10
    assert abs(seconds - 2.5 * len(shots)) < 1.0 and frames >= len(shots)
    walk = [im["src"] for im in META["images"] if im["kind"] == "walkthrough"]
    assert walk == ["docs/assets/walkthrough.gif"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/assets/walkthrough.gif" in readme
    assert "video" not in json.dumps(META["links"])  # OWNER D-86: no video is posted


def test_the_supporting_notes_exist_and_agree_with_the_summary():
    built = (DOCS / "how-i-built-it.md").read_text(encoding="utf-8")
    prd = (DOCS / "prd-one-page.md").read_text(encoding="utf-8")
    flat = " ".join(built.split())
    assert "Claude Code" in flat and "reviewer that never saw the build" in flat
    assert len(prd.split()) < 500
    for heading in ("**Problem.**", "**Who it is for.**", "**What it does.**"):
        assert heading in prd
    cost = f"${SUMMARY['spend_usd']:.2f}"
    assert cost in built
    coverage = _pct(SUMMARY["coverage"]["point"])
    assert f"reached {coverage}" in prd
    for text in (built, prd):
        for m in re.findall(r"\$\d+\.\d\d", text):
            assert m == cost, m
    decisions = (DOCS / "decisions.md").read_text(encoding="utf-8")
    n = len(re.findall(r"^\| (?:OWNER )?D-\d+ \|", decisions, re.M))
    assert f"({n} in all," in built  # the decision count is the log's
    budget = re.search(r"^\| OWNER D-19 \|[^|]*\| Study budget about (\$\d+)", decisions, re.M)
    assert budget and f"hard budget ({budget[1]})" in built and f"{budget[1]} budget" in prd
    assert "$38" in prd and "OWNER D-48" in decisions  # the runs' approval
    passes = {
        len(re.findall(r"verifier pass \d+", (d / "RUN-STATE.md").read_text("utf-8"), re.I))
        for d in (ROOT / "specs").iterdir()
        if (d / "RUN-STATE.md").is_file()
    } - {0}
    assert f"one to {_WORDS[max(passes)]} review passes" in flat
    assert "the PRD's 90% target" in " ".join(prd.split()) or "at least 90%" in prd
    links = META["links"]
    assert links["howBuilt"].endswith("/docs/how-i-built-it.md")
    assert links["prdOnePage"].endswith("/docs/prd-one-page.md")


_WORDS = dict(
    enumerate(
        ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    )
)
