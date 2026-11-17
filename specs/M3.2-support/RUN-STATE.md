# M3.2 run state

**Now:** GREEN (verifier pass 3, 2026-11-17).

## Log
- 2026-11-16 — support sample drawn from run 1 (50 + 20 reserves); judging adapter built offline (18 tests).

- 2026-11-16 — first live judging (OWNER D-60): 25 of 47 judged; the rest blocked by EvalKit parse failures (L-37). Diagnosis: citewatch's kept text glued paragraphs (judges' verbatim quote check failed), and the extractor copied a 1..N citation list into every claim. Spend $1.42 (an earlier report of $2.84 double-counted EvalKit's node and output records) plus $0.21 of probes.
- 2026-11-17 — repair (OWNER D-61): `main_text` breaks lines at block elements; 58 sample pages refetched once (57 ok, times in `support_text_fetches.jsonl`); EvalKit 2181921 (faithfulness extraction without a citation list, spans read against their question); old verdicts discarded; all 49 usable citations judged again for $3.22: claude-opus-5-5 29/48 supported, gpt-6.1-sol 26/48; one citation (1:v-004:gpt-6.1-sol:1) failed extraction twice and is recorded unjudged, never unsupported. Total support spend about $4.85 of the $10 approved. Blind labelling page published.
- 2026-11-17 — owner labels imported (49, all supported, OWNER D-62); calibration with EvalKit's cluster kappa (OWNER D-65) in `results/calibration.json`; `score --finalise` deleted the body cache and EvalKit store.
- 2026-11-17 — verifier pass 1: SUP-01..05 CONFIRMED; every rate, agreement and confusion count recomputed exactly. SUP-06 DISPROVED (gaps never written). Findings: H1 `score` crashed without the `support` extra; M 1:v-062:gpt-6.1-sol:4 was judged on pre-fix text after its D-61 refetch failed; M the private `_Pair` import had no contract test; L kappa read as a precise 0; L finalise would delete any configured path. Fixed per D-67: EvalKit imported at module level in `calibrate.py` so the CLI's guard works, with a no-EvalKit `score` test; 1:v-062 moved to `support_unjudged.jsonl` with its reason (verdicts 96 to 94) and `judge_support.py` now treats a failed refetch as not ok; a contract test on `_Pair`, `cluster_kappa`, `kappa_from`; `support[].kappa` is left out when the owner's labels are all one value; finalise refuses a path that is not a body cache; `results/support_gaps.json` lists every labelled citation's gap and those without a text fetch.

- 2026-11-17 — verifier pass 2: SUP-01..06 CONFIRMED; every rate, confusion count and gap recomputed exactly; a no-EvalKit install scores and writes summary and gaps. Findings: M1 `judge_support.py` would now replace 1:v-062 (the alternative D-67 rejected) and drop unjudged reasons; L the gap list called v-062 "no text fetch"; L the finalise marker was never written; L calibration.json kappa 0 [0,0] and a silently stale calibration.json without EvalKit; nit median. Fixed per D-68.

- 2026-11-17 — verifier pass 3 (focused): every D-68 fix CONFIRMED with adversarial cases (duplicate, unsampled and 24-page fresh labels block both the summary and finalise; 25 distinct pages unblock; selection logic reproduces the committed replacement log and unjudged reasons); recomputation matches; no regression. OPEN HIGH/MEDIUM: 0 (D-26 met). Rows flipped green.

## Known limits
- One citation is unjudged by the AI (repeat extraction failure); it is covered by the owner's label and reported as unjudged.
- The sample ended at 49 usable citations (one stratum short of reserves).
- OWNER D-60 and D-61 say 47 citations; the final sample is 49 (the replacement rule promoted reserves). Two are unjudged by the AI: 1:v-004 (EvalKit extraction failed twice) and 1:v-062 (its D-61 refetch failed, so its text predates the fix, D-67); the owner labelled both.
- Answer-to-fetch gaps: median 0.113 days and max 0.115 days over 48 citations (the D-61 refetch ran hours after run 1); 1:v-062 has no successful text fetch.
- `SupportVerdict.hand_label` stays null; the owner's labels live in `support_labels.jsonl` and join through the page key.
- The support sheet was built in an artifact page, so its blindness (it showed order, host, question, claim and URL only) is attested by the verifier's reading, not reproducible from code.
- `summary.json` kappa uses citewatch's citation-level bootstrap; `calibration.json` uses EvalKit's answer-clustered one. Both are left out or flagged while the owner's labels are constant.
- `scripts/refetch_support_text.py` now marks the cache it writes; caches filled before D-68 carry no marker, so finalise refuses a custom unmarked location (fails safe; the default location is always accepted).
