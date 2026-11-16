# M3.1 acceptance criteria

**MET-01** Presence, weighted and consulted shares per publisher × model × intent (and all intents) × run, per §6.1; zero-citation answers stay in the presence denominator; weighted shares sum to 1 per slice.
**MET-02** Citations per answer (unique URLs, with the raw count), top-10 weighted share and HHI per model × run.
**MET-03** Publisher freshness: median and IQR of lag over dated cited (URL, answer) pairs, with dated count; pages modified after the answer excluded and counted.
**MET-04** Stale-answer rate primary and secondary over valid time-sensitive answers with a dated citation; undated counted; NHS overdue share.
**MET-05** Cross-model overlap per intent and run (both-empty questions excluded and counted), self-overlap per model, normalised overlap, pooled top-20 Jaccard.
**MET-06** Stability: per-model self Jaccard and the change in presence share between runs for each top-10 publisher, with paired bootstrap intervals.
**MET-07** One seeded question-cluster bootstrap (10,000 resamples) for every interval; paired differences with Holm at 0.05; Wilson for proportions from hand checks; tested against hand-computed cases.
**MET-08** `summary.json` validates as `StudySummary`, is byte-identical on a rerun, carries coverage (target 90%), error counts and spend; DuckDB views reproduce the point estimates.
