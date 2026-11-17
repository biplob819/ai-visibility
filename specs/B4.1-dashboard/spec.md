# B4.1 — Findings dashboard and deploy

**Wave 4. Depends on:** M3.1, M3.2, M3.3, S3.1. **Unblocks:** B4.2.

## Goal
One static, self-contained HTML page built from `summary.json` (FR9, D-15): what UK health questions' AI answers cite, how fresh those pages are, and how the two models differ, with a count and an interval beside every percentage, and the scope, coverage, error rates and the two checks on page one.

## Pieces
- `citewatch.report.dashboard.render(summary, study) -> str`: inline SVG charts drawn in Python (no scripts, fonts or styles from elsewhere), each with a table view; light and dark themes from one set of colour roles (dataviz reference palette: Claude slot 1 blue, GPT slot 2 orange); identity never by colour alone (series names in legends and labels, distinct marker shapes).
- Sections, one per `StudySummary` field: headline, scope, share (top publishers by presence, both runs), comparisons, concentration, citations, freshness, stale, nhs_overdue, overlap, stability, coverage, date_accuracy, support, check_methods, error_counts, spend and provenance (hashes, runs, generated_at).
- Cells under 10 answers are marked "directional" (H13).
- `citewatch report --study DIR` writes `DIR/results/site/index.html`; `citewatch report --example` renders the bundled flagship summary to `./citewatch-example/index.html` with no keys.
- Deploy: Cloudflare Pages project for `results/site/` (owner's account; the owner approves the first deploy).

## Not in scope
The post (B4.2), the signal spec (B4.3), the demo (D5.2).
