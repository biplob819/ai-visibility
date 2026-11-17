# ruff: noqa: E501  (inline CSS and SVG markup read best unwrapped)
"""The findings dashboard (node B4.1, FR9, D-15).

One self-contained HTML page from `summary.json`: inline SVG charts drawn here (no scripts,
fonts or styles fetched from anywhere), a table under every chart, a count beside every
percentage, and light and dark themes from one set of colour roles (the dataviz reference
palette: series 1 blue, series 2 orange). Identity never rests on colour alone: each model has
its own marker shape and is named in the legend and every table.

Every summary field has a section (DSH-04); `SECTIONS` lists them in page order.
"""

from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Callable, Sequence

from citewatch.schemas import Interval, StudySummary

DIRECTIONAL_N = 10  # cells resting on fewer answers are marked directional (H13)
TOP_PUBLISHERS = 15
SHARE_TABLE_TOP = 30
SERIES = ("var(--series-1)", "var(--series-2)", "var(--series-3)")
SHAPES = ("circle", "square", "diamond")

SECTIONS = (
    ("headline", "What this study found"),
    ("scope", "Scope"),
    ("checks", "How far to trust these numbers"),
    ("share", "Who gets cited"),
    ("comparisons", "Where the two models differ"),
    ("concentration", "How concentrated the citations are"),
    ("citations", "Citations per answer"),
    ("stale", "Stale answers"),
    ("freshness", "How old the cited pages are"),
    ("nhs_overdue", "NHS pages past their review date"),
    ("overlap", "Do the two models cite the same sources?"),
    ("stability", "Run-to-run stability"),
    ("coverage", "Date coverage"),
    ("date_accuracy", "Date check"),
    ("support", "Support check"),
    ("check_methods", "How each check was made"),
    ("error_counts", "Errors and exclusions"),
    ("provenance", "Provenance"),
)
# StudySummary fields shown in a section named differently (DSH-04 schema walk)
FIELD_SECTION = {
    "runs": "provenance",
    "config_hash": "provenance",
    "questions_sha256": "provenance",
    "preregistration_sha256": "provenance",
    "schema_version": "provenance",
    "generated_at": "provenance",
    "spend_usd": "provenance",
}


def esc(x: object) -> str:
    return html.escape(str(x), quote=True)


def pct(x: float) -> str:
    v = x * 100
    return f"{v:.0f}%" if abs(v) >= 9.5 or v == 0 else f"{v:.1f}%"


def counted(iv: Interval, scale: Callable[[float], str] = pct) -> str:
    """A value with its count and interval: '83% (83/100; 95% CI 75%–90%)'."""
    base = f"{iv.k}/{iv.n}" if iv.k is not None else f"n={iv.n}"
    flag = " · directional" if iv.n < DIRECTIONAL_N else ""
    return f"{scale(iv.point)} ({base}; 95% CI {scale(iv.lo)}–{scale(iv.hi)}){flag}"


def short(model: str | None) -> str:
    if model is None:
        return "Both models"
    return {"claude-sonnet-5-5": "Claude Sonnet 5.5", "gpt-6.1-sol": "GPT-6.1 Sol"}.get(
        model, model
    )


def intent_name(intent: str | None) -> str:
    return "All intents" if intent is None else intent.replace("_", " ").capitalize()


# ---------------------------------------------------------------- chart primitives


def _marker(shape: str, x: float, y: float, fill: str, label: str) -> str:
    title = f"<title>{esc(label)}</title>"
    ring = 'stroke="var(--surface-1)" stroke-width="2"'
    if shape == "square":
        return f'<rect x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" rx="1.5" fill="{fill}" {ring}>{title}</rect>'
    if shape == "diamond":
        pts = f"{x:.1f},{y - 6:.1f} {x + 6:.1f},{y:.1f} {x:.1f},{y + 6:.1f} {x - 6:.1f},{y:.1f}"
        return f'<polygon points="{pts}" fill="{fill}" {ring}>{title}</polygon>'
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{fill}" {ring}>{title}</circle>'


def legend(series: Sequence[str]) -> str:
    items = []
    for i, name in enumerate(series):
        svg = (
            f'<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">'
            f"{_marker(SHAPES[i], 7, 7, SERIES[i], name)}</svg>"
        )
        items.append(f'<span class="key">{svg}{esc(name)}</span>')
    return f'<div class="legend">{"".join(items)}</div>'


def dot_chart(
    rows: Sequence[tuple[str, Sequence[tuple[int, Interval]]]],
    series: Sequence[str],
    caption: str,
    xmax: float = 1.0,
) -> str:
    """Horizontal dot-and-interval rows: one row per label, one marker per series, a whisker
    for the 95% interval. Values in [0, xmax] are shown as percentages."""
    label_w, plot_l, plot_r, row_h, top = 190, 200, 700, 14, 26
    per = max(1, len(series))
    heights = [per * row_h + 10 for _ in rows]
    height = top + sum(heights) + 10
    sx = lambda v: plot_l + (plot_r - plot_l) * max(0.0, min(v, xmax)) / xmax  # noqa: E731
    parts = [
        f'<svg class="chart" viewBox="0 0 720 {height}" role="img" aria-label="{esc(caption)}">',
    ]
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        x = sx(t * xmax)
        parts.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{height - 8}" class="grid"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{top - 12}" class="tick" text-anchor="middle">{pct(t * xmax)}</text>'
        )
    y = top
    for (label, values), h in zip(rows, heights, strict=True):
        parts.append(
            f'<text x="{label_w}" y="{y + h / 2 + 4:.1f}" class="rowlabel" text-anchor="end">{esc(label)}</text>'
        )
        for j, (i, iv) in enumerate(values):
            cy = y + 6 + j * row_h + row_h / 2
            text = f"{label} · {series[i]}: {counted(iv)}"
            parts.append(
                f'<line x1="{sx(iv.lo):.1f}" x2="{sx(iv.hi):.1f}" y1="{cy:.1f}" y2="{cy:.1f}" '
                f'stroke="{SERIES[i]}" stroke-width="2" stroke-linecap="round"><title>{esc(text)}</title></line>'
            )
            parts.append(_marker(SHAPES[i], sx(iv.point), cy, SERIES[i], text))
        y += h
    parts.append("</svg>")
    return (
        f"<figure>{legend(series) if len(series) > 1 else ''}{''.join(parts)}"
        f"<figcaption>{esc(caption)}</figcaption></figure>"
    )


def table(headers: Sequence[str], rows: Sequence[Sequence[object]], caption: str = "") -> str:
    head = "".join(f"<th scope='col'>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f'<div class="tablewrap"><table>{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def details(summary_text: str, inner: str) -> str:
    return f"<details><summary>{esc(summary_text)}</summary>{inner}</details>"


# ---------------------------------------------------------------- sections


def _models(s: StudySummary) -> list[str]:
    return sorted({r.model for r in s.share})


def _presence(s: StudySummary) -> dict[tuple[str, str, str | None, int], Interval]:
    return {
        (r.publisher, r.model, r.intent, r.run): r.share for r in s.share if r.kind == "presence"
    }


def headline(s: StudySummary) -> str:
    models = _models(s)
    run = s.runs[0]
    pres = _presence(s)
    sep = sorted(
        (c for c in s.comparisons if c.separated and c.run == run),
        key=lambda c: (-abs(c.difference.point), c.publisher),
    )
    items = []
    if sep:
        c = sep[0]
        a, b = pres[(c.publisher, c.model_a, None, run)], pres[(c.publisher, c.model_b, None, run)]
        items.append(
            f"<li><strong>{esc(c.publisher)}</strong> appears in {counted(b)} of "
            f"{esc(short(c.model_b))}'s answers but {counted(a)} of {esc(short(c.model_a))}'s "
            f"(run {run}; separated after Holm correction, p = {c.p_holm:.3f}).</li>"
        )
    over = [o for o in s.overlap if o.kind == "cross_model" and o.intent is None and o.run == run]
    if over:
        items.append(
            f"<li>The two models' cited sources overlap little: Jaccard similarity "
            f"{counted(over[0].value)} per question, averaged over questions (run {run}).</li>"
        )
    conc = {(r.model, r.run): r for r in s.concentration}
    if all((m, run) in conc for m in models):
        parts = "; ".join(f"{esc(short(m))} {counted(conc[(m, run)].top10_share)}" for m in models)
        items.append(
            f"<li>Share of citations going to each model's top 10 publishers: {parts}.</li>"
        )
    stale = {(r.model, r.definition): r for r in s.stale if r.intent is None}
    if all((m, "primary") in stale for m in models):
        parts = "; ".join(f"{esc(short(m))} {counted(stale[(m, 'primary')].rate)}" for m in models)
        items.append(
            "<li>Time-sensitive answers whose newest dated source is over 365 days old "
            f"(no fresh source at all): {parts}.</li>"
        )
    return f'<ul class="findings">{"".join(items)}</ul>'


def scope(s: StudySummary) -> str:
    runs = ", ".join(str(r) for r in s.runs)
    return (
        "<p class='scope'>This study measures <strong>sourcing</strong>: which websites two AI "
        "search models cite when asked UK health questions, and how recently those pages were "
        "updated. It does <strong>not</strong> judge whether any answer or page is medically "
        "accurate. 100 pre-registered questions across five intents, asked twice "
        f"(runs {esc(runs)}) of {esc(', '.join(short(m) for m in _models(s)))} with web search, "
        "from London: findings are <strong>directional</strong> for this setup, not a verdict "
        "on AI search in general. Every percentage carries its count and 95% interval.</p>"
    )


def checks(s: StudySummary) -> str:
    cov = s.coverage
    hand = s.error_counts.get("hand_dates", {})
    rows = [
        ("Date coverage", counted(cov), "cited URLs with a resolved date or a logged reason"),
    ]
    overall = next((r for r in s.date_accuracy if r.source == "overall"), None)
    if overall:
        rows.append(
            (
                "Date check",
                counted(overall.within_7_days),
                f"parser within 7 days of the checked date; {s.check_methods.get('date_accuracy', '')}",
            )
        )
    for r in s.support:
        if r.judge != "hand":
            rows.append(
                (
                    f"Support: {short(r.model)} cited, judged by {r.judge}",
                    counted(r.support_rate),
                    "cited page states the claim (AI judge)",
                )
            )
    hand_rows = [r for r in s.support if r.judge == "hand"]
    for r in hand_rows:
        rows.append(
            (
                f"Support: {short(r.model)} cited, owner's check",
                counted(r.support_rate),
                s.check_methods.get("support_hand", "owner-labelled"),
            )
        )
    errs = []
    for m in _models(s):
        e = s.error_counts.get(m, {})
        errs.append(
            f"{short(m)}: {e.get('answers', 0)} answers, {e.get('refusal', 0)} refusals, "
            f"{e.get('transport', 0)} transport errors, {e.get('over_length', 0)} over length"
        )
    note = (
        f"<p class='note'>Errors: {esc('; '.join(errs))}. Date check: "
        f"{hand.get('unjudgeable', 0)} dated pages showed the checker no date and "
        f"{hand.get('checker_could_not_load', 0)} did not load; none is scored.</p>"
    )
    return table(["Check", "Result", "What it measures"], rows) + note


def share(s: StudySummary) -> str:
    models = _models(s)
    pres = _presence(s)
    out = []
    for run in s.runs:
        pooled: dict[str, int] = defaultdict(int)
        for (p, _m, intent, r), iv in pres.items():
            if intent is None and r == run:
                pooled[p] += iv.k or 0
        top = sorted(pooled, key=lambda p: (-pooled[p], p))[:TOP_PUBLISHERS]
        rows = [
            (
                p,
                [
                    (i, pres[(p, m, None, run)])
                    for i, m in enumerate(models)
                    if (p, m, None, run) in pres
                ],
            )
            for p in top
        ]
        out.append(
            dot_chart(
                rows,
                [short(m) for m in models],
                f"Run {run}: share of answers citing each publisher at least once "
                f"(presence share), top {TOP_PUBLISHERS} publishers, 95% intervals.",
            )
        )
        if run == s.runs[0]:
            table_rows = [
                (
                    p,
                    *(
                        counted(pres[(p, m, None, run)]) if (p, m, None, run) in pres else "—"
                        for m in models
                    ),
                )
                for p in sorted(pooled, key=lambda p: (-pooled[p], p))[:SHARE_TABLE_TOP]
            ]
            out.append(
                details(
                    f"Table: top {SHARE_TABLE_TOP} publishers, run {run}",
                    table(["Publisher", *(short(m) for m in models)], table_rows),
                )
            )
    kinds = sorted({r.kind for r in s.share})
    out.append(
        f"<p class='note'>{len(s.share):,} share rows ({', '.join(kinds)}; by publisher, model, "
        "intent and run) are in summary.json.</p>"
    )
    return "".join(out)


def comparisons(s: StudySummary) -> str:
    rows = [
        (
            f"run {c.run}",
            c.publisher,
            f"{short(c.model_a)} − {short(c.model_b)}",
            f"{c.difference.point * 100:+.0f} pts (95% CI {c.difference.lo * 100:+.0f} to {c.difference.hi * 100:+.0f}; n={c.difference.n})",
            f"{c.p_value:.4f}",
            f"{c.p_holm:.4f}",
            "yes" if c.separated else "no",
        )
        for c in sorted(s.comparisons, key=lambda c: (c.run, -abs(c.difference.point), c.publisher))
    ]
    return (
        "<p>Paired differences in presence share for each run's most-cited publishers, with a "
        "two-sided bootstrap p-value and Holm correction (alpha 0.05, pre-registered).</p>"
        + table(
            ["Run", "Publisher", "Difference", "Presence share", "p", "p (Holm)", "Separated"], rows
        )
    )


def concentration(s: StudySummary) -> str:
    models = _models(s)
    rows = [
        (
            f"Run {run}",
            [
                (i, r.top10_share)
                for i, m in enumerate(models)
                for r in s.concentration
                if r.model == m and r.run == run
            ],
        )
        for run in s.runs
    ]
    chart = dot_chart(
        rows,
        [short(m) for m in models],
        "Share of citations going to the model's own top 10 publishers.",
    )
    t = table(
        ["Model", "Run", "Top-10 share", "HHI"],
        [(short(r.model), r.run, counted(r.top10_share), f"{r.hhi:.4f}") for r in s.concentration],
    )
    return chart + details("Table: concentration", t)


def citations(s: StudySummary) -> str:
    rows = [
        (
            short(r.model),
            r.run,
            intent_name(r.intent),
            f"{r.unique_per_answer.point:.2f} (95% CI {r.unique_per_answer.lo:.2f}–{r.unique_per_answer.hi:.2f}; n={r.unique_per_answer.n})",
            f"{r.raw_per_answer:.2f}",
            r.zero_citation,
        )
        for r in s.citations
    ]
    return table(
        [
            "Model",
            "Run",
            "Intent",
            "Unique URLs per answer",
            "Raw citations per answer",
            "Answers citing nothing",
        ],
        rows,
    )


def stale(s: StudySummary) -> str:
    models = _models(s)
    intents = [None, *sorted({r.intent for r in s.stale if r.intent})]
    rows = [
        (
            intent_name(i),
            [
                (j, r.rate)
                for j, m in enumerate(models)
                for r in s.stale
                if r.model == m and r.intent == i and r.definition == "primary"
            ],
        )
        for i in intents
    ]
    chart = dot_chart(
        rows,
        [short(m) for m in models],
        "Primary definition: share of time-sensitive answers whose newest dated citation is "
        "over 365 days old. Per-intent cells rest on few answers and are directional.",
    )
    t = table(
        ["Model", "Intent", "Definition", "Rate", "Undated"],
        [
            (short(r.model), intent_name(r.intent), r.definition, counted(r.rate), r.undated)
            for r in s.stale
        ],
    )
    return chart + details("Table: stale answers (primary and secondary)", t)


def freshness(s: StudySummary) -> str:
    pooled = sorted(
        (r for r in s.freshness if r.model is None and r.median_lag_days is not None),
        key=lambda r: (-r.dated_pages, r.publisher),
    )[:SHARE_TABLE_TOP]
    rows = [
        (
            r.publisher,
            r.dated_pages,
            f"{r.median_lag_days:.0f}",
            f"{r.iqr_days[0]:.0f}–{r.iqr_days[1]:.0f}" if r.iqr_days else "—",
            r.modified_after_answer,
        )
        for r in pooled
    ]
    return (
        "<p>Lag is days from the page's last modified date to the answer that cited it. "
        f"Top {SHARE_TABLE_TOP} publishers by dated pages (both models); per-model rows are in "
        "summary.json.</p>"
        + table(
            [
                "Publisher",
                "Dated citations",
                "Median lag (days)",
                "IQR (days)",
                "Modified after the answer",
            ],
            rows,
        )
    )


def nhs_overdue(s: StudySummary) -> str:
    return table(
        ["Model", "Cited NHS pages past their review-due date"],
        [(short(r.model), counted(r.share)) for r in s.nhs_overdue],
    )


def overlap(s: StudySummary) -> str:
    intents = [None, *sorted({o.intent for o in s.overlap if o.intent})]
    runs = list(s.runs)
    rows = [
        (
            intent_name(i),
            [
                (k, o.value)
                for k, run in enumerate(runs)
                for o in s.overlap
                if o.kind == "cross_model" and o.intent == i and o.run == run
            ],
        )
        for i in intents
    ]
    chart = dot_chart(
        rows,
        [f"Run {r}" for r in runs],
        "Cross-model overlap: Jaccard similarity of the two models' cited publishers per "
        "question, averaged (1 = identical sources, 0 = none in common).",
    )
    t = table(
        ["Kind", "Intent", "Run", "Model", "Value"],
        [
            (
                o.kind,
                intent_name(o.intent),
                o.run or "both",
                short(o.model) if o.model else "—",
                counted(o.value),
            )
            for o in s.overlap
        ],
    )
    return chart + details("Table: every overlap measure", t)


def stability(s: StudySummary) -> str:
    return table(
        ["Model", "Publisher", "Metric", "Value"],
        [(short(r.model), r.publisher or "all", r.metric, counted(r.value)) for r in s.stability],
    )


def coverage(s: StudySummary) -> str:
    return (
        f"<p class='stat'>{counted(s.coverage)}</p><p>Cited URLs with a resolved date or a logged "
        "reason for having none (pre-registered target 90%).</p>"
    )


def date_accuracy(s: StudySummary) -> str:
    method = s.check_methods.get("date_accuracy", "")
    rows = [(r.source, counted(r.within_7_days), counted(r.exact)) for r in s.date_accuracy]
    return f"<p>Held-out pages never used to tune the parser; {esc(method)}.</p>" + table(
        ["Date source", "Within 7 days", "Exact"], rows
    )


def support(s: StudySummary) -> str:
    rows = [
        (
            short(r.model),
            "owner" if r.judge == "hand" else r.judge,
            counted(r.support_rate),
            _agreement(r.hand_agreement, r.support_rate.n),
            counted(r.kappa, lambda x: f"{x:.2f}") if r.kappa else "not reported",
        )
        for r in s.support
    ]
    return (
        "<p>A sample of citations: does the cited page state the claim it was cited for? Two AI "
        "judges from different families and the owner's own check. Kappa is not reported "
        "while the owner's labels are all one value.</p>"
        + table(["Cited model", "Judge", "Supported", "Agreement with owner", "Kappa"], rows)
    )


def _agreement(share: float | None, n: int) -> str:
    """Agreement with its count: the share of the n judged citations the owner also labelled."""
    if share is None:
        return "—"
    k = round(share * n)
    return f"{pct(share)} ({k}/{n})" if abs(share * n - k) < 1e-6 else f"{pct(share)} (n={n})"


def check_methods(s: StudySummary) -> str:
    return table(["Check", "Method"], sorted(s.check_methods.items()))


def error_counts(s: StudySummary) -> str:
    rows = [
        (group, key, val)
        for group, d in sorted(s.error_counts.items())
        for key, val in sorted(d.items())
    ]
    return details(
        "Table: every error and exclusion count", table(["Group", "Count", "Value"], rows)
    )


def provenance(s: StudySummary) -> str:
    rows = [
        ("Runs", ", ".join(str(r) for r in s.runs)),
        ("Generated", s.generated_at.isoformat()),
        ("Spend (USD)", f"${s.spend_usd:.2f}"),
        ("Config hash", s.config_hash),
        ("Questions sha256", s.questions_sha256),
        ("Pre-registration sha256", s.preregistration_sha256),
        ("Results format", s.schema_version),
    ]
    return table(["Item", "Value"], rows)


RENDER: dict[str, Callable[[StudySummary], str]] = {
    "headline": headline,
    "scope": scope,
    "checks": checks,
    "share": share,
    "comparisons": comparisons,
    "concentration": concentration,
    "citations": citations,
    "stale": stale,
    "freshness": freshness,
    "nhs_overdue": nhs_overdue,
    "overlap": overlap,
    "stability": stability,
    "coverage": coverage,
    "date_accuracy": date_accuracy,
    "support": support,
    "check_methods": check_methods,
    "error_counts": error_counts,
    "provenance": provenance,
}

CSS = """
:root{color-scheme:light;--surface-0:#ffffff;--surface-1:#fcfcfb;--line:#e4e3df;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#6b6a66;--accent:#2a78d6;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
--surface-0:#121211;--surface-1:#1a1a19;--line:#33332f;--text-primary:#f0efec;
--text-secondary:#c3c2b7;--text-muted:#a3a29b;--accent:#3987e5;--series-1:#3987e5;
--series-2:#d95926;--series-3:#199e70}}
:root[data-theme="dark"]{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;
--line:#33332f;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#a3a29b;
--accent:#3987e5;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:1.9rem;line-height:1.2;margin:0 0 6px}
h2{font-size:1.25rem;margin:40px 0 10px;padding-top:12px;border-top:1px solid var(--line)}
p,li{color:var(--text-secondary)} strong{color:var(--text-primary)}
.lede{font-size:1.05rem;margin:0 0 20px}
.findings li{margin:6px 0;color:var(--text-primary)}
.scope{background:var(--surface-1);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.note{font-size:.9rem;color:var(--text-muted)}
.stat{font-size:1.6rem;font-weight:650;color:var(--text-primary);margin:4px 0}
nav{font-size:.9rem;margin:16px 0 8px;display:flex;flex-wrap:wrap;gap:6px 14px}
nav a,a{color:var(--accent)}
figure{margin:12px 0;background:var(--surface-1);border:1px solid var(--line);border-radius:8px;padding:12px}
figcaption{font-size:.88rem;color:var(--text-muted);margin-top:6px}
.chart{width:100%;height:auto;display:block}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .tick{font-size:11px;fill:var(--text-muted)}
.chart .rowlabel{font-size:12px;fill:var(--text-primary)}
.legend{display:flex;gap:18px;font-size:.9rem;color:var(--text-secondary);margin-bottom:6px}
.legend .key{display:inline-flex;align-items:center;gap:6px}
.tablewrap{overflow-x:auto;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:.88rem}
caption{text-align:left;color:var(--text-muted);padding-bottom:4px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--text-secondary);font-weight:600}
td{color:var(--text-primary);font-variant-numeric:tabular-nums}
details{margin:8px 0} summary{cursor:pointer;color:var(--accent);font-size:.92rem}
footer{margin-top:48px;font-size:.85rem;color:var(--text-muted)}
"""


def render(summary: StudySummary, study: str = "UK health") -> str:
    """`study` completes "What AI search cites for … questions"."""
    """The dashboard as one HTML document."""
    nav = "".join(f'<a href="#{key}">{esc(title)}</a>' for key, title in SECTIONS)
    body = []
    for key, title in SECTIONS:
        body.append(f'<section id="{key}"><h2>{esc(title)}</h2>{RENDER[key](summary)}</section>')
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>citewatch: {esc(study)}</title>"
        '<meta name="description" content="Which sources AI search answers cite for UK health '
        'questions, and how fresh those pages are.">'
        f"<style>{CSS}</style></head><body><main>"
        f"<h1>What AI search cites for {esc(study)} questions</h1>"
        "<p class='lede'>citewatch asked two AI search models 100 pre-registered questions, "
        "twice, and recorded every source they cited and how recently each page was updated.</p>"
        f"<nav aria-label='Sections'>{nav}</nav>"
        + "".join(body)
        + "<footer>Built by citewatch from summary.json. Open source: "
        '<a href="https://github.com/biplob819/ai-visibility">github.com/biplob819/ai-visibility</a>.'
        "</footer></main></body></html>\n"
    )
