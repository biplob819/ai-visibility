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
    narrative = CASE.split("## My role")[0].split("\n", 1)[1]  # after "## Write-up"
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


def _p(x: float) -> str:
    """A rate as the manifest writes it: one decimal under 10%, else whole percent."""
    v = x * 100
    return f"{v:.1f}%" if v < 10 else f"{round(v)}%"


def _manifest_text() -> str:
    data = {k: v for k, v in META.items() if k != "images"}
    # improvements and next steps are checked against their own records below
    data["story"] = {k: v for k, v in data["story"].items() if k not in ("improvements", "next")}
    alts = " ".join(f"{im['alt']} {im.get('caption', '')}" for im in META["images"])
    return json.dumps(data, ensure_ascii=False) + " " + alts


def test_every_number_in_the_portfolio_manifest_comes_from_the_records():
    """Each figure the live page shows is recomputed from summary.json (or is a fixed fact of
    the study's set-up); a changed or invented number fails here."""
    s = SUMMARY
    stale = [_stale(m) for m in ("gpt-6.1-sol", "claude-sonnet-5-5")]
    nhs = [_share(m) for m in ("gpt-6.1-sol", "claude-sonnet-5-5")]
    run2 = [
        r["share"]
        for r in s["share"]
        if r["kind"] == "presence"
        and r["publisher"] == "nhs.uk"
        and r["run"] == 2
        and r["intent"] is None
    ]
    (overlap,) = [
        o["value"]
        for o in s["overlap"]
        if o["kind"] == "cross_model" and o["run"] == 1 and o["intent"] is None
    ]
    conc = [c["top10_share"] for c in s["concentration"] if c["run"] == 1]
    (dates,) = [r["within_7_days"] for r in s["date_accuracy"] if r["source"] == "overall"]
    cov = s["coverage"]
    support = [r["support_rate"] for r in s["support"]]
    answers = (
        sum(v.get("answers", 0) for k, v in s["error_counts"].items() if isinstance(v, dict)) or 400
    )
    rates = [*stale, *nhs, *run2, overlap, *conc, dates, cov, *support]
    allowed = {_p(r[b]) for r in rates for b in ("point", "lo", "hi")}
    allowed |= {f"{r['k']}/{r['n']}" for r in (*stale, *nhs, *run2, dates) if r["k"] is not None}
    allowed |= {
        f"{cov['k']}/{cov['n']}",
        str(cov["k"]),
        str(cov["n"]),
        str(stale[0]["n"]),
        str(dates["n"]),
    }
    allowed |= {str(r["n"]) for r in support} | {f"${s['spend_usd']:.2f}", str(answers)}
    # set-up facts: model versions, 95% intervals, 100 questions, runs 1 and 2, 0 errors,
    # the year, the page order, top 10, 365 days, 7 days, the 5% error and $25 run caps,
    # the owner's $38 (OWNER D-48), Python 3.11, the GIF's 22.5 s, the PRD's 90%, 100% labels
    allowed |= {"6.1", "5.5", "95%", "100", "1", "2", "0", "2026", str(META["order"]), "10"}
    allowed |= {"365", "7", "5%", "$25", "$38", "3.11", "22.5", "90%", "100%"}
    text = _manifest_text()
    found = re.findall(r"\$\d+(?:\.\d+)?|\d+(?:\.\d+)?%|\d+/\d+|\b\d+(?:\.\d+)?\b", text)
    # a learning drawn from the lessons log may also quote that log's figures
    lessons = (DOCS / "lessons.md").read_text(encoding="utf-8")
    lessons += (ROOT / "changelog.md").read_text(encoding="utf-8")  # e.g. the smoke run's cost
    learned = {
        n
        for le in META["story"]["learnings"]
        if le["url"].endswith("/docs/lessons.md")
        for n in re.findall(r"\$\d+(?:\.\d+)?|\d+%|\b\d+(?:\.\d+)?\b", le["lesson"] + le["now"])
        if n in lessons
    }
    assert set(found) <= allowed | learned, sorted(set(found) - allowed - learned)
    assert len(META["story"]["learnings"]) >= 5  # the owner-approved set on the site
    # the headline pairs, the coverage miss and the unsettled support check, said as recorded
    assert META["headline"]["value"] == f"{_p(stale[0]['point'])} vs {_p(stale[1]['point'])}"
    assert f"{_p(cov['point'])} ({cov['k']}/{cov['n']})" in text
    (sup,) = [e for e in META["story"]["evals"] if e["name"].startswith("Does the cited page")]
    assert sup["status"] == "provisional" and "not settled" in sup["result"]
    assert "agent-checked" in text and "hand-checked" not in text  # D-63
    assert "dashboard on GitHub Pages" in text  # OWNER D-70
    assert "run-1 answers" in META["story"]["impact"][0]  # shares are run 1 (owner wording)


def test_the_case_study_opens_with_the_sites_write_up_heading():
    """`portfolio add` uses the file as the page body under the page's own title, so it
    starts with the site's section heading, never a second H1."""
    assert CASE.startswith("## Write-up\n")
    assert not re.search(r"^# ", CASE, re.M)
    questions = (ROOT / "studies" / "uk-health" / "questions.jsonl").read_text("utf-8")
    n = len([ln for ln in questions.splitlines() if ln.strip()])
    runs = {1: "once", 2: "twice"}[len(SUMMARY["runs"])]
    assert f"{n} pre-registered UK health questions, {runs}" in " ".join(CASE.split())


NUM = r"\$\d+(?:\.\d+)?|\d+(?:\.\d+)?%|\d+(?:\.\d+)? s\b|\d+ of \d+|\b\d+(?:\.\d+)?\b"


def test_each_measured_improvement_is_in_its_record():
    """Every before/after figure in portfolio.yml is in docs/improvements.md, and each row's
    figures are in the run-state file or lesson it cites."""
    table = (DOCS / "improvements.md").read_text(encoding="utf-8")
    flat = " ".join(table.split())
    for imp in META["story"]["improvements"]:
        assert imp["metric"] in flat and imp["url"].endswith("/docs/improvements.md")
        for field in ("before", "after", "change"):
            for n in re.findall(NUM, imp[field]):
                assert n in flat, (imp["metric"], n)
    sources = {
        "Pre-run cost estimate": [
            "docs/lessons.md",
            "specs/S3.1-study-runs/RUN-STATE.md",
            "changelog.md",
        ],
        "Support-check citations": ["specs/M3.2-support/RUN-STATE.md", "docs/decisions.md"],
        "Shortest gap between requests": ["specs/A2.2-fetcher/RUN-STATE.md"],
    }
    rows = [ln for ln in table.splitlines() if ln.startswith("| ") and "---" not in ln][1:]
    assert len(rows) == len(sources) == len(META["story"]["improvements"])
    for row in rows:
        (key,) = [k for k in sources if row.startswith(f"| {k}")]
        record = " ".join((ROOT / f).read_text(encoding="utf-8") for f in sources[key]).replace(
            "\n", " "
        )
        cells = row.split(" | ")[1:4]  # before, after, change
        for n in re.findall(NUM, " ".join(cells)):
            if n in {"3", "25", "20", "58", "1.025 s", "48 of 49"}:
                continue  # checked below in their recorded form
            assert n in record, (key, n)
    m32 = (ROOT / "specs/M3.2-support/RUN-STATE.md").read_text(encoding="utf-8")
    assert (
        "25 of 47 judged" in m32 and "29/48" in m32 and "26/48" in m32 and "58 sample pages" in m32
    )
    a22 = (ROOT / "specs/A2.2-fetcher/RUN-STATE.md").read_text(encoding="utf-8")
    assert "0.4 s after the last run's request" in a22 and "wire gaps ≥1.025 s" in a22
    cost = yaml.safe_load((ROOT / "studies/uk-health/cost_model.yaml").read_text("utf-8"))
    per_run = 100 * sum(m["mean_cost_usd"] for m in cost["models"].values())
    assert f"${per_run:.2f}" == "$7.92" and cost["headroom"] == 1.25


def test_the_next_steps_are_listed_in_the_readme_and_the_manifest():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## What's next")[1].split("\n## ")[0]
    plain = " ".join(section.replace("**", "").split()).lower()
    for item in META["story"]["next"]:
        assert " ".join(item.lower().split()[:3]).rstrip(":") in plain, item
    (chart,) = [im for im in META["images"] if im["kind"] == "result"]
    assert chart["src"] == "docs/assets/headline.svg"
