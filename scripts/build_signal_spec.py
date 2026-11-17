# ruff: noqa: E501  (the page is HTML prose in a template string)
"""B4.3: the one-page signal spec (FR10, US6).

    uv run python scripts/build_signal_spec.py            # HTML and PDF (needs Google Chrome)
    uv run python scripts/build_signal_spec.py --html-only

Writes docs/signal-spec.html from studies/uk-health/results/summary.json and prints it to
docs/signal-spec.pdf on one A4 page with headless Chrome. Every quoted finding is printed by
`citewatch.report.dashboard.counted`, so it carries its count and interval and traces to the
summary by construction.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import get_args

from citewatch.report.dashboard import counted, esc, short
from citewatch.schemas import StudySummary
from citewatch.schemas.cards import ImprovementCode

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "studies" / "uk-health" / "results" / "summary.json"
HTML = ROOT / "docs" / "signal-spec.html"
PDF = ROOT / "docs" / "signal-spec.pdf"
CHROME = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
)
CLAUDE, GPT = "claude-sonnet-5-5", "gpt-6.1-sol"
MODELS = (CLAUDE, GPT)
CODES = get_args(ImprovementCode)

CSS = """
@page{size:A4;margin:12mm 13mm}
*{box-sizing:border-box}
body{margin:0;font:9.1pt/1.38 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#1b1b1a}
h1{font-size:16pt;margin:0 0 1mm;letter-spacing:-.01em}
.sub{color:#52514e;margin:0 0 3mm}
h2{font-size:9.6pt;text-transform:uppercase;letter-spacing:.06em;color:#2a78d6;margin:3.2mm 0 1.2mm}
p{margin:0 0 1.4mm}
ul{margin:0 0 1mm;padding-left:4.2mm} li{margin:0 0 .7mm}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 7mm}
table{border-collapse:collapse;width:100%;font-size:8.3pt;margin:.5mm 0 1mm}
th,td{text-align:left;padding:.9mm 1.4mm;border-bottom:.3pt solid #d9d8d3;vertical-align:top}
th{color:#52514e;font-weight:600}
.box{border:.4pt solid #d9d8d3;border-radius:2mm;padding:2mm 2.6mm;background:#fafaf8}
.foot{margin-top:2.5mm;font-size:7.6pt;color:#6b6a66}
strong{color:#000}
"""


def _pick(s: StudySummary):
    pres = {
        (r.publisher, r.model, r.run): r.share
        for r in s.share
        if r.kind == "presence" and r.intent is None
    }
    over = next(
        o.value for o in s.overlap if o.kind == "cross_model" and o.intent is None and o.run == 1
    )
    conc = {(r.model, r.run): r.top10_share for r in s.concentration}
    stale = {r.model: r.rate for r in s.stale if r.intent is None and r.definition == "primary"}
    acc = next(r.within_7_days for r in s.date_accuracy if r.source == "overall")
    return pres, over, conc, stale, acc


def stamp(html_without_stamp: str) -> str:
    """A short hash of the page, put in its title so the PDF's metadata shows which build it is."""
    import hashlib

    return hashlib.sha256(html_without_stamp.encode()).hexdigest()[:12]


def render(s: StudySummary) -> str:
    page = _render(s)
    return page.replace("STAMP", stamp(page))


def _render(s: StudySummary) -> str:
    pres, over, conc, stale, acc = _pick(s)
    answers = sum(v["answers"] for k, v in s.error_counts.items() if k in (CLAUDE, GPT))
    questions = max(r.share.n for r in s.share if r.kind == "presence" and r.intent is None)
    findings = [
        f"<strong>nhs.uk</strong> is cited in {counted(pres[('nhs.uk', GPT, 1)])} of "
        f"{short(GPT)} answers and {counted(pres[('nhs.uk', CLAUDE, 1)])} of {short(CLAUDE)}'s.",
        f"The two models' sources barely overlap: Jaccard {counted(over)} per question.",
        f"Top-10 publishers hold {counted(conc[(GPT, 1)])} of {short(GPT)}'s citation weight "
        f"against {counted(conc[(CLAUDE, 1)])} of {short(CLAUDE)}'s (each answer counts "
        "equally, split over its cited URLs; the interval leans upward because the top 10 is "
        "re-picked in each resample).",
        f"Time-sensitive answers with no dated source under a year old: {short(GPT)} "
        f"{counted(stale[GPT])}; {short(CLAUDE)} {counted(stale[CLAUDE])}.",
    ]
    fields = [
        ("Presence and weighted share", "per publisher × model × intent × run, with 95% intervals"),
        ("Cited instead", "who the models cite when they leave a publisher out"),
        ("Freshness", "effective date, its source, lag to the answer, stale rate, review-due"),
        ("Readability", "robots.txt outcome, fetch errors, documents vs pages, hidden dates"),
        ("Support", "does the cited page state the claim (two AI judges + a human check)"),
        (
            "Improvement codes",
            f"{len(CODES)} per-publisher reasons, each with a fix and its evidence",
        ),
    ]
    rows = "".join(f"<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>" for a, b in fields)
    tiers = [
        ("Open", "the MIT tool and the published UK study; run your own questions on your keys"),
        ("Publisher", "your domain's card refreshed each cycle, with its improvement report"),
        ("Sector", "a full panel for one sector and country; JSON feed and dashboard"),
        ("Lab", "custom question sets and models, raw citation records and the support check"),
    ]
    tier_rows = "".join(f"<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>" for a, b in tiers)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>citewatch signal spec STAMP</title><style>{CSS}</style></head><body>
<h1>citewatch: a sourcing signal for AI search</h1>
<p class="sub">Which websites AI search answers cite, how fresh those pages are, and what a publisher
can change. Built on an open-source, pre-registered study: {questions} UK health questions,
{len(MODELS)} models, {len(s.runs)} runs.</p>
<div class="box"><strong>What the first study found</strong> (run 1 unless noted; both runs pooled for stale):
<ul>{"".join(f"<li>{f}</li>" for f in findings)}</ul>
<p>Date coverage {counted(s.coverage)}; dates checked on held-out pages: within 7 days
{counted(acc)} (agent-checked, owner-approved). Sourcing only: no claim about medical accuracy.</p>
</div>
<div class="grid"><div>
<h2>Fields</h2><table>{rows}</table>
<h2>Buyers</h2>
<ul>
<li><strong>Publishers</strong> (health bodies, charities, NHS trusts, comms teams): are we cited, for which
questions, who is cited instead, and what would help.</li>
<li><strong>AI labs</strong>: sourcing quality by model and topic: concentration, staleness and support,
measured the same way across models.</li>
<li><strong>Agencies and researchers</strong>: a reproducible panel with error bars, not screenshots.</li>
</ul>
</div><div>
<h2>Delivery</h2>
<ul>
<li>Re-runs of a frozen question set (started by hand today; scheduling is planned); a run manifest pins models, code and config.</li>
<li>JSON results (format v1) and per-publisher cards; a static dashboard; a domain lookup (library function today, demo page planned).</li>
<li>Planned for v0.1.0: threshold checks, so a run fails in CI when a tracked metric crosses its bound.</li>
<li>Every share and rate ships with its count and 95% interval.</li>
</ul>
<h2>Pricing logic</h2>
<p><strong>Unit of value:</strong> one tracked question set × one model × one run, delivered with
intervals. Cost scales with questions × models × runs (this study: {answers} answers for ${s.spend_usd:.2f} of API spend).</p>
<table>{tier_rows}</table>
<p>No price points yet: tiers are set by panel size, refresh cadence and access to raw records.</p>
<h2>Limits</h2>
<ul><li>Directional: one country, two models, 100 questions per study.</li>
<li>Dates only from what pages state; unreadable pages are counted, never guessed.</li></ul>
</div></div>
<p class="foot">github.com/biplob819/ai-visibility · dashboard: biplob819.github.io/ai-visibility ·
generated from summary.json ({esc(s.generated_at.date().isoformat())}, runs
{", ".join(str(r) for r in s.runs)})</p>
</body></html>
"""


def chrome() -> str | None:
    for c in CHROME:
        if Path(c).is_file() or shutil.which(c):
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html-only", action="store_true")
    a = ap.parse_args()
    s = StudySummary.model_validate_json(SUMMARY.read_text(encoding="utf-8"))
    HTML.write_text(render(s), encoding="utf-8", newline="\n")
    print(f"wrote {HTML.relative_to(ROOT)}")
    if a.html_only:
        return 0
    exe = chrome()
    if exe is None:
        print("Google Chrome not found; run with --html-only", file=sys.stderr)
        return 2
    subprocess.run(
        [
            exe,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={PDF}",
            HTML.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    print(f"wrote {PDF.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
