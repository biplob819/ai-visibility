# S3.1 run state

**Now:** GREEN (verifier pass 2, 2026-11-17).

## Log
- 2026-11-16 — run 1 (gate G1 passed): 200 answers, 0 errors, $7.55; extract 1,219 citations; support sample drawn before fetch, with the sampler and kept-text code not yet committed (committed unchanged in 4629dbf five minutes later); 566 pages fetched (409 ok, 97 robots-disallowed); fetch and storage audits OK; coverage 88%.
- 2026-11-16 — run 2 (gate G2 passed at 2 h 0 m, code unchanged since run 1's 45abb41; run 2 started from e5f4e73): 200 answers, 0 errors, $7.48; 218 new pages fetched (144 ok, 41 robots-disallowed); audits OK. Both runs scored: coverage 89% of 841 cited URLs (target 90%, reported below target). Errors 0% per model; Claude over 150 words 24/100 per run, GPT 0.
- RUN-03: ledger, raw costs and recomputation from usage agree exactly per run (`scripts/reconcile_spend.py`). The provider consoles are the remaining check, by hand.
- 2026-11-17 — verifier pass 1: RUN-01..03 CONFIRMED (gate G1 refused each mutated condition; errors 0/100 per model per run; parity reproduced; costs recomputed from the provider usage blocks match the ledger exactly); RUN-04 manifests and committed data CONFIRMED, frozen pending labels. OPEN HIGH/MEDIUM: 0.

- 2026-11-17 — labels in (M3.2, M3.3 green); run data frozen by hash (`tests/test_study_freeze.py`: answers, citations, consulted, page_meta, fetch log, spend ledger, both samples, both manifests); RUN-03 proved by `tests/runs/test_reconcile.py` (both runs reconcile exactly; a run with no records now fails, where it had printed OK).

- 2026-11-17 — verifier pass 2: RUN-01..04 CONFIRMED (cost recomputed from 420 raw usage blocks: $7.5534 + $7.4783 = $15.03; every frozen hash equals the file at the commit that added it; page_meta rebuilt from raw fetch records with 0 differences; score re-run byte-identical). Lows: raw/ask and the support records were not hash-pinned (now pinned in `tests/test_study_freeze.py`); D-31 search billing is an assumption. OPEN HIGH/MEDIUM: 0 (D-26 met). Rows flipped green.

## Known limits
- Run 1's fetch ran from a working tree holding the then-uncommitted sampler and kept-text code; the sample is deterministic from citations and seed, and all sample text was rebuilt by the D-61 refetch, so no result depends on it.
- Run 2 re-requested 1 cited page that differs only by a trailing slash, 17 uncited pages listed as sitemaps, and about 195 sitemaps after transient failures (by design); every page stayed within 3 requests and the audit passes.
- OWNER D-61 says 51 sample pages; 58 were refetched (every sample or reserve page that fetched ok).
- Gate G2 freezes runners, extractors, `study.yaml` and the questions, not schemas or `config_hash`; nothing else changed between these runs. `finished_at` is truncated to the second.
- Gate G1 does not check provider keys or user-agent contact up front (keys fail before any call), checks the measured cost model rather than A2.4's catalog status, and matches 16-hex hash prefixes.
- `reconcile_spend.py` recomputes from citewatch's usage summary; the verifier's recomputation from the raw provider usage blocks agreed exactly.
- Model snapshots are the alias ids the providers return, not dated snapshots.
- D-31 counts only OpenAI `search` actions as billed; if `open_page` and `find_in_page` were billed too, spend would be about $0.47 more per run (about $15.96 in total). The provider console check by hand is still to do.
- `reconcile_spend.py` allows 10% between ledger, raw costs and recomputation (they agree exactly); the raw records themselves are hash-pinned.
