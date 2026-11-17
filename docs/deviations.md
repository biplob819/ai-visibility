# Deviations from the pre-registration

The questions, settings, seeds, metric definitions (Tech Spec §6), thresholds and exclusions
were frozen in [`preregistration.md`](preregistration.md) before run 1 (OWNER D-47, D-51; sha256
`9e227483cc387386…`, pinned by `tests/test_questions_freeze.py`). Nothing in it was edited after
the first answer. This page lists every place where the study, as run and analysed, departs
from that plan or had to read it where it was silent, with the decision that records it and its
effect on the published numbers. Decision ids link to [`decisions.md`](decisions.md).

## Metric readings where §6 is silent (no effect on any definition)

| Decision | What changed | Effect on results |
|---|---|---|
| D-56 | §6.3: a page dated after the answer still counts as the answer's newest dated citation for the stale rules; NHS overdue is over cited (page, answer) pairs whose publisher or group is nhs.uk; every top-k list keeps all publishers tied at the cut; spend counts only the scored runs; bootstrap p-values are (count + 1) / (B + 1) | Defines figures the plan left open; no headline changes direction |
| D-55 | `summary.json` gained citations per answer, paired comparisons and NHS overdue rows | Additional reported figures, all defined in §6 |

## The support check (§8.1, node M3.2)

| Decision | What changed | Effect on results |
|---|---|---|
| OWNER D-61 | Page text was glued at paragraph breaks, which broke the judges' quote check; the text was fixed, the 58 sample pages refetched once, earlier verdicts discarded and all citations judged again | Support rates come from the second judging only |
| D-67, D-68 | One citation (1:v-062) whose refetch failed is recorded unjudged rather than replaced by its reserve, because a replacement would have had no owner label; another (1:v-004) is unjudged after EvalKit failed twice | GPT-cited judge rates are over 23 citations, the owner's over 25 |
| OWNER D-62 | The owner labelled all 49 citations supported, one to two seconds apart, and confirmed the labels; they are reported beside both judges with that pace stated | Judge–owner kappa is not reported (it is 0 by construction when one rater is constant); the true support rate is not settled |
| OWNER D-65 | Judges are calibrated against the owner's labels with EvalKit's cluster kappa | An added analysis (`calibration.json`) |

## The date check (§8.2, node M3.3)

| Decision | What changed | Effect on results |
|---|---|---|
| OWNER D-63, D-64 | The held-out dates were read by a fresh-context agent that never saw the parser's output, and approved by the owner with no edits, instead of being hand-labelled | Every place the result appears says "agent-checked, owner-approved" |
| D-68 | Seven pages the agent could not load are counted and never scored | Within 7 days: 18 of 27 judgeable pages; the undated row is 2 of 4 |
| D-67 | The sample was drawn from pages cited in runs 1–2 (not smoke-run pages), which the plan implied but did not state; a script re-draws it | None: the committed sample re-draws exactly |

## Reported against plan, not changed

- **Date coverage** is 89% (745 of 841 cited URLs) against the plan's 90% target, reported as below target.
- **Over-length answers** (48 of Claude's 200 answers, none of GPT's) are included, as pre-registered, and counted.
- **Model snapshots** are the alias ids the providers return, not dated snapshots (S3.1 known limits).
- **Cost** was $15.03 for the two study runs, inside the $38 the owner approved (OWNER D-48).

## Outside the analysis

Where the dashboard and demo are hosted (OWNER D-70, D-73), how the improvement report is
worded (D-69, D-71, D-72, D-75) and the post's wording (D-76) change presentation only, not any
number.
