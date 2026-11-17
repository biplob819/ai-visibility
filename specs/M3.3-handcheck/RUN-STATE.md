# M3.3 run state

**Now:** GREEN (verifier pass 3, 2026-11-17).

## Log
- 2026-11-17 — sample drawn with `study_pages` (pages cited in runs 1–2) and seed 52: 55 (50 dated across 6 sources + 5 undated). A fresh-context agent read the 55 live pages without the parser's output; the owner reviewed and froze them with no edits. Within 7 days 18/27 judgeable (67%, Wilson 48–81%); 23 dated pages show a reader no date.
- 2026-11-17 — verifier pass 1: HND-02 CONFIRMED; HND-03 numbers reproduced exactly; HND-01 DISPROVED (the sample did not re-draw: the draw's run 1–2 filter was not in code). Findings H1 (finalise read only the first label row), H2 (stale labels still produced accuracy rows), H3 (re-draw), M (unjudgeable pages not counted, no method label, wording against D-63). Fixed per D-67: `study_pages` plus a re-draw test against the committed sample; the held-out rule reads every row (`labels_meta`), blocks the summary's accuracy rows and finalise, and scores only current-resolver labels once 25 exist; `error_counts.hand_dates` counts labels, stale labels and unjudgeable pages; `check_methods.date_accuracy` says "agent-checked, owner-approved"; wording fixed in the spec, module docstring and data card.

- 2026-11-17 — verifier pass 2: HND-01..03 CONFIRMED (re-draw equal; accuracy and counts reproduced; eight bypass cases blocked). Findings: M1 duplicate fresh rows and M2 fresh rows outside the sample satisfied the 25-label rule; M3 load failures counted as "no date" (and one scored as a correct undated page); L wording in Tech Spec §8.2 and the PRD; L no command re-runs the draw; L the fingerprint covers only `citewatch/dates`. Fixed per D-68 (distinct sampled pages; `checker_loaded`; wording; `scripts/draw_hand_sample.py`); the fingerprint scope is a known limit.

- 2026-11-17 — verifier pass 3 (focused): every D-68 fix CONFIRMED with adversarial cases (duplicate, unsampled and 24-page fresh labels block both the summary and finalise; 25 distinct pages unblock; selection logic reproduces the committed replacement log and unjudged reasons); recomputation matches; no regression. OPEN HIGH/MEDIUM: 0 (D-26 met). Rows flipped green.

## Known limits
- A dated page the checker loaded but could not date is left out of its accuracy rate and counted in `error_counts.hand_dates.unjudgeable` (17 of 50); 7 pages the checker could not load (6 dated, 1 undated) are counted in `checker_could_not_load` and never scored. Per-source rates are conditional on a reader seeing a date: visible-text dates have no exclusions, schema.org 7 of 13.
- Every judged page was either exact or more than 7 days off, so the within-7-days and exact rates are equal on this sample.
- The checker is an AI agent, approved by the owner without edits (OWNER D-63, D-64); it is not an independent human check. Three loaded pages (h07, h26, h45) may add a date with scripts the agent could not run; they count as showing no date.
- Month-only dates (h19, h55) were read as the 1st of the month; h10 (App Store, no year) was read as the current year.
- The resolver fingerprint covers `src/citewatch/dates/*.py` only; a change elsewhere (URL canonicalisation, robots, schemas, dateutil) that shifted effective dates would not trip the held-out rule.
- `score --finalise` falls back to all label URLs when `hand_sample.jsonl` is missing (the summary publishes nothing without a sample); label rows are imported out of band (`score --labels` is not built), so a future importer must keep `checker_loaded` (the freeze test would catch its loss).
