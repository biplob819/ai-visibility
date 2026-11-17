# B4.3 — Signal spec

**Wave 4. Depends on:** M3.1, S3.1. **Unblocks:** B4.4.

## Goal
A one-page PDF that turns the study into a data product a data PM would find credible (FR10, US6): the fields of the signal (from `PageMeta`, the cards and the measured gaps), who buys it (publishers, AI labs, agencies), how it is delivered, and the pricing logic as a unit of value and tiers without price points. Every quoted finding comes from `summary.json`.

## Pieces
- `scripts/build_signal_spec.py`: renders `docs/signal-spec.html` from `summary.json` (quoted findings printed with `citewatch.report.dashboard.counted`, so each carries its count and interval) and prints it to `docs/signal-spec.pdf` with headless Chrome on A4.
- `docs/signal-spec-checklist.md`: the data-product checklist (buyer, unit of value, delivery, pricing logic, fields, limits), each item pointing at the line that meets it.
- Tests: the PDF has exactly one page; every percentage in the HTML equals a `summary.json` interval printed with its count; the checklist's sections are present.

## Not in scope
Price points (the PRD asks for tiers without prices); the post (B4.2).
