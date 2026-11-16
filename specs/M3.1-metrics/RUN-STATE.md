# M3.1 run state

**Now:** built; verifier pass 1.

## Log
- 2026-11-16 — node_start GO. Built `citewatch.metrics` (data, stats, compute, summary, views) and `citewatch score`; numpy and duckdb added. A hand-worked 4-question, 2-run study checks every figure; DuckDB views reproduce presence shares; the golden replay now rebuilds `summary.json` byte for byte. Smoke data: coverage 92% (target 90%). Summary rows added (D-55).

## Known limits
- Top-10 share and pooled top-20 Jaccard are biased upward under the bootstrap on small samples (fewer distinct publishers in a resample), so the point can sit at the low edge of its interval; intervals are widened to include the point, never the reverse. Smaller with 100 questions; reported as a limit.
- Freshness rows (median and IQR) carry no bootstrap interval; the schema has none (§6.3 asks for median, IQR and count).
- Stale and overdue figures pool both runs, clustered by question; per-run figures are not in the summary.
