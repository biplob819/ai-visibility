# N1.4 run state

**Now:** green.

## History
- 2026-11-15 — spec and criteria written.
- 2026-11-15 — started; `studies/uk-health/RUBRIC.md` committed before any question (QST-01, commit 291ef84). 100 drafts (20 per intent, 50 time-sensitive) seeded into the owner's review page https://claude.ai/artifact/LKga9AEnuwUJvfAw3ipqmY (db collection `questions`, freeze flag `meta/state`). When the owner approves, the builder reads the set back, writes `questions.jsonl`, the pre-registration and the data card, and records both hashes.

- 2026-11-16 — verifier pass 1 CONFIRMED QST-01..04 (approved set matches the file, 0 mismatches; one-byte changes fail the freeze; every data-card claim checked against code). OPEN HIGH/MEDIUM: 0. Lows applied before run 1: the owner aligned the time-sensitive flags with the rubric and re-froze (OWNER D-51, 57 time-sensitive); alpha 0.05 two-sided with Holm frozen; a test ties study.yaml and the rubric hash to the pre-registration; NICE and Mind matched only as written; data card names robots and sitemap reads and describes `cited_text` and `encrypted_content` accurately; the question-set limits are pre-registered. Rows flipped green.

## Known limits
- The lint catches listed names and domains only: spaced or hyphenated variants (`Mayo-Clinic`), unlisted brands and "what's the NHS advice" pass it; the owner's review is the check for those, and the frozen set was hand-checked.
- v-032 asks two linked things (which injections, who can get them); v-031, v-096 use "now"; v-080 asks what current guidance says. Approved by the owner as natural phrasing.
- The review page shows the pre-D-51 flags; `questions.jsonl` and D-51 are the record.
