# A2.4 run state

**Now:** green.

## Log
- 2026-11-16 — verifier pass 1 CONFIRMED SMK-01..05 (ledger matches raw costs line by line; cost model recomputed independently; every replay mutation fails; replay passes with network denied, an odd time zone and no sitemap cache). OPEN HIGH/MEDIUM: 0. Lows applied: the golden builder reads sitemap dates from page_meta candidates; `cost_model.yaml` rejects zeros, duplicate models and bad YAML cleanly; replay tests marked `golden`; parity.md regenerated; L-34 wording. Rows flipped green.

## Known limits
- Rebuilding `page_meta` in a fresh clone re-downloads sitemaps (the cache is local, D-53), so live lastmods may differ from the committed ones; the committed `page_meta.jsonl` is the record for a frozen run.
- GPT cost counts `search` actions only (D-31); `open_page` calls and OpenAI's cache-write tokens are unpriced. If billed, about $0.008 more per answer, well inside the estimate.
