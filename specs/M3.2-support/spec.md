# M3.2 — Support check

**Wave 3. Depends on:** A2.1, A2.2. **Unblocks:** B4.1.

## Goal
Measure how often a cited page actually states the claim it is cited for (Tech Spec §8.1): 50 sampled citations, judged by two models through EvalKit's faithfulness scorer and hand-labelled blind by the owner, with agreement reported and every page body deleted afterwards.

## Pieces
- `score --sample-support`: seeded stratified sample, drawn after run 1's extract and before its fetch (SUP-01). Done for uk-health: 50 + 20 reserves.
- The fetcher keeps those pages' main text (nav, footer and forms stripped) in the body cache outside the repo.
- `citewatch.support.judge`: replacement rule, evidence sentences, EvalKit `faithfulness()` with both judges, verdicts (SUP-02, SUP-03). Paid: owner approval before the live call.
- Blind labelling sheet for the owner; support rate per model and judge with Wilson intervals; judge–hand agreement and Cohen's kappa with bootstrap intervals; answer-to-fetch gap per item (SUP-05, SUP-06).
- `score --finalise`: deletes the body cache and EvalKit store and asserts both are gone; only `SupportVerdict` rows remain (SUP-04).
