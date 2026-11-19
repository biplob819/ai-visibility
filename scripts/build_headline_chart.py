"""Write docs/assets/headline.svg: the study's headline numbers with their 95% intervals.

    uv run python scripts/build_headline_chart.py

Every value is read from studies/uk-health/results/summary.json; the colours and marks are the
dashboard's (Claude a blue circle, GPT an orange square), so the chart reads as the same
system. tests/test_headline_chart.py rebuilds it and checks it matches the committed file.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "studies" / "uk-health" / "results" / "summary.json"
OUT = ROOT / "docs" / "assets" / "headline.svg"

MODELS = (
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "#3987e5"),
    ("gpt-6.1-sol", "GPT-6.1 Sol", "#d95926"),
)
INK, MUTED, GRID, SURFACE = "#33332f", "#6b6a64", "#e5e4df", "#fbfbfa"
W, LEFT, RIGHT, TOP, ROW = 760, 250, 40, 92, 66


def rows(summary: dict) -> list[tuple[str, str, dict[str, dict]]]:
    def share(model: str, run: int) -> dict:
        (r,) = [
            r["share"]
            for r in summary["share"]
            if r["kind"] == "presence"
            and r["publisher"] == "nhs.uk"
            and r["model"] == model
            and r["run"] == run
            and r["intent"] is None
        ]
        return r

    def stale(model: str) -> dict:
        (r,) = [
            r["rate"]
            for r in summary["stale"]
            if r["definition"] == "primary" and r["intent"] is None and r["model"] == model
        ]
        return r

    return [
        ("Answers citing nhs.uk", "run 1", {m: share(m, 1) for m, _, _ in MODELS}),
        ("Answers citing nhs.uk", "run 2", {m: share(m, 2) for m, _, _ in MODELS}),
        (
            "Time-sensitive answers with no",
            "dated source under a year old (both runs)",
            {m: stale(m) for m, _, _ in MODELS},
        ),
    ]


def _pct(x: float) -> str:
    v = x * 100
    return f"{v:.1f}%" if v < 10 else f"{round(v)}%"


def build(summary: dict) -> str:
    data = rows(summary)
    h = TOP + ROW * len(data) + 56
    plot = W - LEFT - RIGHT

    def x(v: float) -> float:
        return LEFT + v * plot

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" '
        'role="img" aria-labelledby="t d" '
        'font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        '<title id="t">What AI search cites for UK health questions</title>',
        '<desc id="d">'
        + escape(
            "; ".join(
                f"{a} {b}: "
                + ", ".join(
                    f"{name} {_pct(v[m]['point'])} ({v[m]['k']}/{v[m]['n']}, 95% CI "
                    f"{_pct(v[m]['lo'])} to {_pct(v[m]['hi'])})"
                    for m, name, _ in MODELS
                )
                for a, b, v in data
            )
        )
        + "</desc>",
        f'<rect width="{W}" height="{h}" fill="{SURFACE}"/>',
        f'<text x="24" y="34" font-size="18" font-weight="700" fill="{INK}">'
        "What AI search cites for UK health questions</text>",
        f'<text x="24" y="56" font-size="13" fill="{MUTED}">100 pre-registered questions, each '
        "model asked twice with web search on. Dots: estimates; lines: 95% intervals.</text>",
    ]
    lx = LEFT
    for _, name, colour in MODELS:  # legend: identity is never colour alone (circle vs square)
        mark = (
            f'<circle cx="{lx + 5}" cy="76" r="5" fill="{colour}"/>'
            if colour == MODELS[0][2]
            else f'<rect x="{lx}" y="71" width="10" height="10" rx="1.5" fill="{colour}"/>'
        )
        out.append(mark + f'<text x="{lx + 16}" y="80" font-size="13" fill="{INK}">{name}</text>')
        lx += 150
    base = TOP + ROW * len(data)
    for t in (0, 0.25, 0.5, 0.75, 1):
        out.append(
            f'<line x1="{x(t):.1f}" y1="{TOP}" x2="{x(t):.1f}" y2="{base}" '
            f'stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{x(t):.1f}" y="{base + 18}" font-size="12" fill="{MUTED}" '
            f'text-anchor="middle">{round(t * 100)}%</text>'
        )
    for i, (a, b, vals) in enumerate(data):
        y0 = TOP + ROW * i + 18
        out.append(
            f'<text x="24" y="{y0 + 6}" font-size="13" fill="{INK}">{escape(a)}</text>'
            f'<text x="24" y="{y0 + 24}" font-size="12" fill="{MUTED}">{escape(b)}</text>'
        )
        for j, (m, _, colour) in enumerate(MODELS):
            v = vals[m]
            y = y0 + j * 18
            out.append(
                f'<line x1="{x(v["lo"]):.1f}" y1="{y}" x2="{x(v["hi"]):.1f}" y2="{y}" '
                f'stroke="{colour}" stroke-width="2" stroke-linecap="round"/>'
            )
            px = x(v["point"])
            if j == 0:
                out.append(
                    f'<circle cx="{px:.1f}" cy="{y}" r="5" fill="{colour}" '
                    f'stroke="{SURFACE}" stroke-width="2"/>'
                )
            else:
                out.append(
                    f'<rect x="{px - 5:.1f}" y="{y - 5}" width="10" height="10" rx="1.5" '
                    f'fill="{colour}" stroke="{SURFACE}" stroke-width="2"/>'
                )
            label = f"{_pct(v['point'])} ({v['k']}/{v['n']})"
            anchor, lx2 = ("start", x(v["hi"]) + 8) if v["hi"] < 0.8 else ("end", x(v["lo"]) - 8)
            out.append(
                f'<text x="{lx2:.1f}" y="{y + 4}" font-size="12" fill="{INK}" '
                f'text-anchor="{anchor}">{label}</text>'
            )
    out.append(
        f'<text x="24" y="{h - 16}" font-size="11" fill="{MUTED}">Source: citewatch, '
        "studies/uk-health/results/summary.json. Measures sourcing, not medical accuracy.</text>"
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> int:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    OUT.write_text(build(summary), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
