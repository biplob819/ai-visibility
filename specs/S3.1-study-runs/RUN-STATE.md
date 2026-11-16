# S3.1 run state

**Now:** both runs collected and audited; freeze waits for the owner's support and date labels (M3.2, M3.3).

## Log
- 2026-11-16 — run 1 (gate G1 passed): 200 answers, 0 errors, $7.55; extract 1,219 citations; support sample drawn before fetch; 566 pages fetched (409 ok, 97 robots-disallowed); fetch and storage audits OK; coverage 88%.
- 2026-11-16 — run 2 (gate G2 passed at 2 h 0 m, code unchanged since run 1's e5f4e73): 200 answers, 0 errors, $7.48; 218 new pages fetched (144 ok, 41 robots-disallowed); audits OK. Both runs scored: coverage 89% of 841 cited URLs (target 90%, reported below target). Errors 0% per model; Claude over 150 words 24/100 per run, GPT 0.
- RUN-03: ledger, raw costs and recomputation from usage agree exactly per run (`scripts/reconcile_spend.py`). The provider consoles are the remaining check, by hand.

## Known limits
