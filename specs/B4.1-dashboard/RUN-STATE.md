# B4.1 run state

**Now:** verifier pass 1 fixes applied; deploying to GitHub Pages (OWNER D-70).

## Log
- 2026-11-17 — built: `citewatch report` (`--study`, `--example`, `--title`), self-contained page, 18 sections.
- 2026-11-17 — verifier pass 1: DSH-01, DSH-02, DSH-04 CONFIRMED (207 interval strings traced to single summary Intervals, no untraceable number; deterministic build). Findings fixed: M per-intent stale rows now marked directional (H13); M headline and charts show a never-cited publisher as 0 of the model's answers instead of crashing or leaving a gap; M scope, lede and description from the summary and study.yaml (questions, intents, runs, location, word limit), not the flagship; L headline wording for top-10 share (citation weight) and pooled stale; comparison headers; share_change in pts; freshness says effective date; NHS capitalised; coverage target and over-length explained on page one; run-2 share table; charts scroll at phone width; row headers. Deploy chosen: GitHub Pages (OWNER D-70).

## Known limits
- The top-10 share bootstrap re-picks the top 10 in each resample, so its interval leans upward of the point (noted in the chart caption).
- Freshness lag is shown pooled across models per publisher; per-model rows are in summary.json.
- SVG marker titles sit inside `role=img`; screen readers get the data from the tables.
