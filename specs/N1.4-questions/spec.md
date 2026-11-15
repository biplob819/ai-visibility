# N1.4 — Questions, pre-registration, data card

**Wave 1. Depends on:** N1.1. **Unblocks:** A2.4 and the study runs.

## Goal
The flagship study's 100 questions are written to a rubric fixed before any question exists, and the metric definitions, thresholds, exclusions and seeds are frozen with the questions before run 1, so no number can be redefined after the data is seen (D-7, H10).

## Outputs
- `studies/uk-health/RUBRIC.md` (QST-01): natural UK phrasing, no publisher or brand names, one need per question, at most 30 words, and the time-sensitive rule (the right answer could change within 12 months: services, eligibility, waiting times, prices, current guidance), each flag with a reason.
- `studies/uk-health/questions.jsonl` (QST-02): 100 questions, 20 per intent, at least 8 time-sensitive per intent; `citewatch` lints the mechanical rules (unique ids, intent declared, word limit, no domain names, no known publisher names).
- `docs/preregistration.md` (QST-03): Tech Spec §6 verbatim plus seeds and exclusions; sha256 of it and of the questions recorded in `decisions.md`; a data-freeze test fails if either changes afterwards.
- `DATA_CARD.md` (QST-04): what is collected, what is discarded, politeness, quoted-span policy, limits; present tense only for what is already true (L-9).

## Owner work
The owner writes the 100 questions (the builder may draft candidates for the owner to edit, clearly marked as drafts) and approves the freeze.

## Out of scope
Running anything (A2.4, S3.1).
