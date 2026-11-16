# S3.1 acceptance criteria

**RUN-01** Run 1 asked, extracted and fetched; gate G1 refuses each unmet condition (hashes not recorded, no measured cost model or estimate over the cap, prices older than 7 days, dirty tree); post-run audits pass: errors below 5% per model, parity report, fetch-log audit, coverage reported, spend in the ledger.
**RUN-02** Run 2 under unchanged runner and extractor code (gate G2 refuses a change since run 1's commit or a start within 2 hours of run 1 finishing); only new URLs fetched.
**RUN-03** Spend reconciled: the ledger, the raw records' costs and a recomputation from provider usage agree; any gap above 10% explained.
**RUN-04** A manifest per run (config hash, git SHA, model snapshots, start and end times, answers); data committed and frozen.
