# M3.1 — Metrics and statistics

**Wave 3. Depends on:** A2.1, A2.3. **Unblocks:** B4.1, B4.3.

## Goal
Compute every metric of Tech Spec §6 (frozen in `docs/preregistration.md`) from the study's data files, with the §6.6 statistics, and write `results/summary.json`; nothing is defined here that §6 does not define.

## Design
- `citewatch.metrics.data` loads answers, citations, consulted sources, page metadata and questions into per-answer records (valid = no transport error and no refusal; P(a) = publishers of the unique canonical URLs).
- Every bootstrapped metric is a function of per-question arrays, so one seeded resample matrix W (10,000 × questions, seed `bootstrap`) gives every interval by matrix products (EvalKit D-37). Percentile 95% intervals; a point outside its percentile interval widens the interval to include it (logged in the limits).
- Model comparisons: paired bootstrap differences of presence share over shared questions for the top-10 publishers; two-sided p-values, Holm across the family, separated at 0.05 (pre-registered).
- Wilson intervals for hand checks and coverage.
- `generated_at` is the latest timestamp in the data, so the same data always gives the same bytes.
- DuckDB views over the JSONL files as an independent SQL oracle for the point estimates.
- `citewatch score` writes `results/summary.json`; the support and hand samples stay with M3.2 and M3.3.

## Out of scope
Support check (M3.2), hand date check (M3.3), dashboard (B4.1).
