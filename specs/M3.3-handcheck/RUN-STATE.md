# M3.3 run state

**Now:** labels imported (agent-checked, owner-approved, OWNER D-63, D-64); verifier pass 1 fixes applied (D-67); pass 2 next.

## Log
- 2026-11-17 — sample drawn with `study_pages` (pages cited in runs 1–2) and seed 52: 55 (50 dated across 6 sources + 5 undated). A fresh-context agent read the 55 live pages without the parser's output; the owner reviewed and froze them with no edits. Within 7 days 18/27 judgeable (67%, Wilson 48–81%); 23 dated pages show a reader no date.
- 2026-11-17 — verifier pass 1: HND-02 CONFIRMED; HND-03 numbers reproduced exactly; HND-01 DISPROVED (the sample did not re-draw: the draw's run 1–2 filter was not in code). Findings H1 (finalise read only the first label row), H2 (stale labels still produced accuracy rows), H3 (re-draw), M (unjudgeable pages not counted, no method label, wording against D-63). Fixed per D-67: `study_pages` plus a re-draw test against the committed sample; the held-out rule reads every row (`labels_meta`), blocks the summary's accuracy rows and finalise, and scores only current-resolver labels once 25 exist; `error_counts.hand_dates` counts labels, stale labels and unjudgeable pages; `check_methods.date_accuracy` says "agent-checked, owner-approved"; wording fixed in the spec, module docstring and data card.

## Known limits
- A dated page the checker cannot date is left out of its accuracy rate and counted in `error_counts.hand_dates.unjudgeable` (23 of 50). Per-source rates are conditional on a reader seeing a date: visible-text dates have no exclusions, schema.org 7 of 13.
- Every judged page was either exact or more than 7 days off, so the within-7-days and exact rates are equal on this sample.
- The checker is an AI agent, approved by the owner without edits (OWNER D-63, D-64); it is not an independent human check. Seven pages did not load for the agent and are counted as showing no date.
- Month-only dates (h19, h55) were read as the 1st of the month; h10 (App Store, no year) was read as the current year.
