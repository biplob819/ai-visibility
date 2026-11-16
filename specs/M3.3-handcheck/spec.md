# M3.3 — Hand date check

**Wave 3. Depends on:** A2.3. **Unblocks:** B4.1.

## Goal
Measure how accurate the chosen dates are on pages the resolver was never tuned on (Tech Spec §8.2, D-6): 50 dated cited pages stratified by date source plus 5 undated, labelled by the owner blind to the parser's answer, scored within 7 days and exactly, with Wilson intervals.

## Pieces
- `citewatch.handcheck`: seeded proportional sample with a floor of 5 per source, tuning-set URLs excluded, only pages that fetched `ok`; written once.
- Blind labelling page (artifact) for the owner; labels imported as `HandDateLabel` rows with the resolver fingerprint.
- `accuracy()` → `AccuracyRow`s for `summary.json`; the held-out rule: a resolver change after labelling blocks publishing until 25 fresh labels.
- Drawn after run 2's fetch, so the sample covers both runs' cited pages.
