# M3.1 run state

**Now:** green.

## Log
- 2026-11-16 — node_start GO. Built `citewatch.metrics` (data, stats, compute, summary, views) and `citewatch score`; numpy and duckdb added. A hand-worked 4-question, 2-run study checks every figure; DuckDB views reproduce presence shares; the golden replay now rebuilds `summary.json` byte for byte. Smoke data: coverage 92% (target 90%). Summary rows added (D-55).
- 2026-11-16 — verifier pass 1: independent recomputation matched every point estimate (636/636 share rows on smoke) and every bootstrap interval to 1e-12. DISPROVED MET-04 (stale dropped pages dated after the answer, M1; NHS overdue denominator, M2), MET-05 (top-20 by name order at ties, M3), MET-08 (spend was the whole ledger, M4). Fixed per D-56 with tests; lows applied: p-values never 0, undated pages counted by outcome, boundary tests (365 days, review due on the answer day, transport error).
- 2026-11-16 — verifier pass 2: independent exact-fraction recomputation, 0 mismatches on smoke and tiny; D-56 readings confirmed against the frozen text. DISPROVED MET-07 only: comparison ties at the top-10 cut were split by float rounding (1/5 + 2/5 != 3/5). Fixed: ranking on integer counts (stability too); a test that fails on the old code. Lows applied: ledger lines must carry this study's name; NHS pages with no review date counted by outcome (`error_counts.nhs_no_review_date`); tests for secondary stale at 365 days, an NHS page missing from page_meta, stability ties and the pooled cut.
- 2026-11-16 — verifier pass 3 (focused) CONFIRMED MET-07; the independent recomputation reports 0 mismatches on smoke and tiny; no regression. OPEN HIGH/MEDIUM: 0 (D-26 met). Rows flipped green.

## Known limits
- Top-10 share and pooled top-20 Jaccard are biased upward under the bootstrap on small samples (fewer distinct publishers in a resample), so the point can sit at the low edge of its interval; intervals are widened to include the point, never the reverse. Smaller with 100 questions; reported as a limit.
- Freshness rows (median and IQR) carry no bootstrap interval; the schema has none (§6.3 asks for median, IQR and count).
- Stale and overdue figures pool both runs, clustered by question; per-run figures are not in the summary.
- Freshness median and IQR are over (URL, answer) pairs; `dated_pages` counts unique URLs, so it is not the number of lag observations.
- Holm corrects within each run's family; two runs are two families.
- DuckDB views reproduce presence share only; the other figures are cross-checked by the independent recomputation in verifier pass 1.
- Resample totals use BLAS matrix products, not `math.fsum`; ulp-level differences across BLAS builds have not changed summary bytes so far, and CI replays the golden on Linux, macOS and Windows.
- Lag uses the UTC date of `answered_at`.
- Pages dated after the answer count as the answer's newest source (D-56a), so an answer whose copy the model read was older is not called stale: the stale rate is a lower bound in that respect.
- `test_stability_top_list_includes_ties` checks `top_with_ties`, not `stability()` end to end; stability membership was checked against exact fractions by verifier pass 3.
