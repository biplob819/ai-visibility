# M3.2 run state

**Now:** judged; waiting for the owner's blind labels (https://claude.ai/artifact/HQwemfBkBqyGWHhZYuwK3s).

## Log
- 2026-11-16 — support sample drawn from run 1 (50 + 20 reserves); judging adapter built offline (18 tests).

- 2026-11-16 — first live judging (OWNER D-60): 25 of 47 judged; the rest blocked by EvalKit parse failures (L-37). Diagnosis: citewatch's kept text glued paragraphs (judges' verbatim quote check failed), and the extractor copied a 1..N citation list into every claim. Spend $1.42 (an earlier report of $2.84 double-counted EvalKit's node and output records) plus $0.21 of probes.
- 2026-11-17 — repair (OWNER D-61): `main_text` breaks lines at block elements; 58 sample pages refetched once (57 ok, times in `support_text_fetches.jsonl`); EvalKit 2181921 (faithfulness extraction without a citation list, spans read against their question); old verdicts discarded; all 49 usable citations judged again for $3.22: claude-opus-5-5 29/48 supported, gpt-6.1-sol 26/48; one citation (1:v-004:gpt-6.1-sol:1) failed extraction twice and is recorded unjudged, never unsupported. Total support spend about $4.85 of the $10 approved. Blind labelling page published.

## Known limits
- One citation is unjudged by the AI (repeat extraction failure); it is covered by the owner's label and reported as unjudged.
- The sample ended at 49 usable citations (one stratum short of reserves).
