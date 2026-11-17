# B4.2 — The post and charts

**Wave 4. Depends on:** B4.1. **Unblocks:** B4.4.

## Goal
A readable write-up of the study for a data-PM audience (US6): it opens with the main finding and the scope statement, shows its charts, says how far to trust each number, and links the dashboard and the signal spec. Every number comes from `summary.json` (or, for publisher counts, `domain_cards.json`).

## Pieces
- `citewatch.report.post.render(summary, cards)`: one self-contained HTML page (the dashboard's CSS and chart primitives), published at `/post/` beside the dashboard by the Pages workflow; `citewatch report` writes it too.
- Charts generated from `summary.json`: top publishers by presence share, stale answers by intent, cross-model overlap by intent.
- `docs/post-review-b9.md`: the B9 checklist (never advise publishers on gaming AI answers), filled in and signed off by the owner.
- Tests: opens with the finding and scope; links the signal spec and dashboard; every printed value traces to `summary.json`; the B9 checklist exists and is signed off.

## Not in scope
Social copy; the project page (D5.3).
