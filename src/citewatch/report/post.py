# ruff: noqa: E501  (prose and markup read best unwrapped)
"""The write-up (node B4.2, US6): one self-contained page beside the dashboard.

Every value is printed from `summary.json` through the dashboard's `counted`, so it carries its
count and interval; publisher counts come from `domain_cards.json`. It opens with the main finding
and the scope statement and links the dashboard and the signal spec (PST-01). It never advises
publishers on gaming AI answers (B9): the only advice is about making dates and pages readable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from citewatch.metrics.stats import wilson
from citewatch.report import dashboard as d
from citewatch.schemas import DomainCard, Interval, StudySummary

DASHBOARD = "../"
SIGNAL_SPEC = "https://github.com/biplob819/ai-visibility/blob/main/docs/signal-spec.pdf"
REPO = "https://github.com/biplob819/ai-visibility"


def _lead(s: StudySummary, run: int):
    pres = d._presence(s)
    sep = sorted(
        (c for c in s.comparisons if c.separated and c.run == run),
        key=lambda c: (-abs(c.difference.point), c.publisher),
    )
    return pres, sep


def _top_for(s: StudySummary, model: str, run: int, n: int) -> list[tuple[str, Interval]]:
    rows = [
        (r.publisher, r.share)
        for r in s.share
        if r.kind == "presence" and r.intent is None and r.model == model and r.run == run
    ]
    return sorted(rows, key=lambda x: (-(x[1].k or 0), x[0]))[:n]


def _prose(intent: str | None) -> str:
    """An intent for running text: lower case, but NHS stays NHS."""
    return d.intent_name(intent).lower().replace("nhs", "NHS")


def render(summary: StudySummary, cards: Sequence[DomainCard], title: str = "UK health") -> str:
    s = summary
    d.CONTEXT.clear()
    d.CONTEXT.update(title=title, location=None, word_limit=None)
    models = d._models(s)
    a, b = models[0], models[-1]
    run = s.runs[0]
    pres, sep = _lead(s, run)
    lead = sep[0] if sep else None
    over = {(o.intent, o.run): o.value for o in s.overlap if o.kind == "cross_model"}
    conc = {(r.model, r.run): r.top10_share for r in s.concentration}
    stale = {(r.model, r.intent): r.rate for r in s.stale if r.definition == "primary"}
    secondary = {
        r.model: r.rate for r in s.stale if r.definition == "secondary" and r.intent is None
    }
    overdue = {r.model: r.share for r in s.nhs_overdue}
    acc = next((r for r in s.date_accuracy if r.source == "overall"), None)
    hand = s.error_counts.get("hand_dates", {})
    codes = Counter(i.code for c in cards for i in c.improvement)
    code_words = {
        "stale": "pages dated more than a year before a time-sensitive answer",
        "robots_unreadable": "robots.txt files citewatch could not read",
        "undated": "pages with no date citewatch could find",
        "hidden_date": "pages dated only where readers cannot see it",
        "not_html": "documents rather than web pages",
        "blocked": "pages refused to automated readers",
        "intent_absent": "topics where a publisher is never cited",
        "fetch_error": "pages that failed to load",
        "robots_blocked": "pages robots.txt disallows",
        "unsupported": "claims the support check did not find on the page",
    }
    top_codes = ", ".join(
        f"{code_words.get(c, c)} ({n} publishers)" for c, n in codes.most_common(3)
    )
    q = d._questions(s)
    intents = sorted({r.intent for r in s.share if r.intent})
    answers = sum(v.get("answers", 0) for k, v in s.error_counts.items() if k in models)
    nruns = len(s.runs)
    cell_q = sorted({r.rate.n // nruns for r in s.stale if r.intent is not None})
    both_runs = lambda p: all(  # noqa: E731
        any(c.separated and c.publisher == p for c in s.comparisons if c.run == r) for r in s.runs
    )
    by_src = {r.source: r.within_7_days for r in s.date_accuracy}
    visible = by_src.get("visible_text")
    hidden_src = [by_src[k] for k in ("sitemap", "http_header", "page_age") if k in by_src]
    hidden_k = sum(iv.k or 0 for iv in hidden_src)
    hidden_n = sum(iv.n for iv in hidden_src)
    hand_rows = [r for r in s.support if r.judge == "hand"]

    def nm(m: str) -> str:
        return d.esc(d.short(m))

    lead_html = ""
    lo_m = a
    if lead:
        pa = d._share_of(s, pres, lead.publisher, lead.model_a, run)
        pb = d._share_of(s, pres, lead.publisher, lead.model_b, run)
        hi_m, hi, lo_m, lo = (
            (lead.model_b, pb, lead.model_a, pa)
            if pb.point > pa.point
            else (lead.model_a, pa, lead.model_b, pb)
        )
        lead_html = (
            f"<p class='lede'>Ask {nm(hi_m)} a UK health question with web search on (run {run}) and "
            f"<strong>{d.esc(lead.publisher)}</strong> is among its sources in "
            f"{d.counted(hi)} of answers. Ask {nm(lo_m)} the same question and it is "
            f"{d.counted(lo)}. Same questions, same day, same place: the two models lean on "
            "different parts of the web.</p>"
        )
    others = [p for p, _ in _top_for(s, lo_m, run, 4) if not lead or p != lead.publisher][:3]
    others_html = (
        ", ".join(f"{d.esc(p)} ({d.counted(d._share_of(s, pres, p, lo_m, run))})" for p in others)
        if lead
        else ""
    )

    charts = [
        d.share(s).split("<details>")[0],
        d.stale(s).split("<details>")[0],
        d.overlap(s).split("<details>")[0],
    ]
    over_all = over.get((None, run))
    over_by_intent = sorted(
        ((i, over[(i, run)]) for i in intents if (i, run) in over), key=lambda x: x[1].point
    )
    stale_gap = sorted(
        ((i, stale[(a, i)], stale[(b, i)]) for i in intents if (a, i) in stale and (b, i) in stale),
        key=lambda x: -(abs(x[2].point - x[1].point)),
    )

    body = f"""
<p class="kicker">citewatch study · {d.esc(title)} · runs {", ".join(str(r) for r in s.runs)}</p>
<h1>Who AI search cites for {d.esc(title)} questions, and how fresh it is</h1>
{lead_html}
{d.scope(s)}
<p>The full numbers are on the <a href="{DASHBOARD}">dashboard</a>; what this could become as a
data product is in the one-page <a href="{SIGNAL_SPEC}">signal spec</a>. Code, data and every
decision are in the <a href="{REPO}">open-source repository</a>.</p>

<h2>What was measured</h2>
<p>{q} questions across {len(intents)} intents ({d.esc(", ".join(_prose(i) for i in intents))}),
written and frozen before any answer was seen, were each asked of {nm(a)} and {nm(b)} with web
search, in {len(s.runs)} runs: {answers} answers in all. citewatch recorded every source each
answer cited, then visited each cited page, politely and only where robots.txt allowed, to find
when it was last reviewed, modified or published. Every share and rate below carries its count
and a 95% interval.</p>

<h2>1. The models lean on different sources</h2>
<p>{nm(lo_m) if lead else ""} spreads its citations across the wider NHS family and
others; its most cited publishers in run {run} were {others_html}.</p>
{charts[0]}
<p>The gap for {d.esc(lead.publisher) if lead else "the top publisher"}
{"holds in every run and" if lead and both_runs(lead.publisher) else ""} survives a Holm
correction across each run's most cited publishers. {len([c for c in s.comparisons if c.separated])} of
{len(s.comparisons)} paired comparisons separate the models.</p>

<h2>2. They rarely cite the same sources</h2>
<p>Comparing the publishers each model cites for the same question, the average overlap
(Jaccard similarity) is {d.counted(over_all) if over_all else "—"} in run {run}. It ranges from
{d.counted(over_by_intent[0][1]) if over_by_intent else "—"} for
{d.esc(_prose(over_by_intent[0][0])) if over_by_intent else ""} to
{d.counted(over_by_intent[-1][1]) if over_by_intent else "—"} for
{d.esc(_prose(over_by_intent[-1][0])) if over_by_intent else ""} questions.</p>
{charts[2]}

<h2>3. One model concentrates, the other spreads</h2>
<p>The top 10 publishers hold {d.counted(conc[(b, run)])} of {nm(b)}'s citation weight and
{d.counted(conc[(a, run)])} of {nm(a)}'s (each answer counts equally; the interval leans upward
because the top 10 is re-picked in every resample).</p>

<h2>4. Time-sensitive answers often rest on old pages</h2>
<p>For questions where the right answer can change (services, eligibility, waiting times,
prices, guidance), an answer is counted as stale when even its newest dated source is over a year
old (its date as last reviewed, else modified, else published). That was true of {d.counted(stale[(b, None)])} of {nm(b)}'s time-sensitive answers and
{d.counted(stale[(a, None)])} of {nm(a)}'s, both runs pooled. On the looser definition, any
dated source over a year old, the figures are {d.counted(secondary[b])} and
{d.counted(secondary[a])}. Citations of NHS pages already past their own review-due date:
{nm(b)} {d.counted(overdue[b])}, {nm(a)} {d.counted(overdue[a])}.</p>
{charts[1]}
<p>Per-intent cells rest on {cell_q[0] if cell_q else 0} to {cell_q[-1] if cell_q else 0} questions each and are directional; the largest gap is for
{d.esc(_prose(stale_gap[0][0])) if stale_gap else ""} questions
({nm(b)} {d.counted(stale_gap[0][2], directional=True) if stale_gap else ""}; {nm(a)}
{d.counted(stale_gap[0][1], directional=True) if stale_gap else ""}).</p>

<h2>How far to trust these numbers</h2>
<ul>
<li><strong>Dates.</strong> citewatch found a date, or a logged reason for having none, for
{d.counted(s.coverage)} of cited URLs, just under the study's 90% target. On {hand.get("labels", 0)}
held-out pages (agent-checked, owner-approved), the parser was within 7 days on
{d.counted(acc.within_7_days) if acc else "—"} of the pages that could be judged. Dates read from
visible page text were within 7 days on {d.counted(visible) if visible else "—"}; dates from
sitemaps, HTTP headers or the search tool's page age, which readers never see, on
{d.counted(wilson(hidden_k, hidden_n))}.</li>
<li><strong>Support.</strong> On a sample of citations, two AI judges from different families
found the claim stated on the cited page in {"; ".join(f"{d.counted(r.support_rate)} ({nm(r.model)} cited, judged by {nm(r.judge)})" for r in s.support if r.judge != "hand")}.
The owner's own check, made at a quick pace of one to two seconds per citation, found
{"; ".join(f"{d.counted(r.support_rate)} ({nm(r.model)} cited)" for r in hand_rows)} supported
(two citations the judges could not assess are in the owner's count only). The judges and the
owner disagree, and this check cannot settle the true rate.</li>
<li><strong>Scope.</strong> One country, two models, {q} questions, two runs. This is a
measurement of sourcing, not of medical accuracy, and not advice for anyone choosing a health
source.</li>
</ul>

<h2>What publishers can take from it</h2>
<p>citewatch builds a card for each of the {len(cards)} cited publishers: how often each model
cites it, by topic, who is cited instead, and readability problems found on its cited pages. Across
all cards the most common were {top_codes}. The advice is about being readable and current: a visible, marked-up
date and an available robots.txt. It is not, and will not be, advice on gaming AI answers.</p>

<h2>Method and reproducing it</h2>
<p>The questions, settings, seeds, metrics and the alpha of 0.05 with Holm correction were
pre-registered before the first answer. Intervals come from a question-cluster bootstrap; counts
from Wilson intervals. The two study runs cost ${s.spend_usd:.2f} in API calls. Anyone can rerun
it with their own keys: install citewatch from the <a href="{REPO}">repository</a>, then run
<code>citewatch ask</code>, <code>extract</code>, <code>fetch</code> and <code>score</code>.</p>
"""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Who AI search cites for {d.esc(title)} questions</title>"
        f'<meta name="description" content="Two AI search models, {q} {d.esc(title)} questions: '
        'which sources they cite and how fresh those pages are.">'
        f"<style>{d.CSS}.kicker{{font-size:.85rem;color:var(--text-muted);margin:0 0 6px}}"
        "code{font-size:.9em}</style></head><body><main>"
        + body
        + '<footer>citewatch · <a href="../">dashboard</a> · '
        f'<a href="{REPO}">github.com/biplob819/ai-visibility</a></footer></main></body></html>\n'
    )
