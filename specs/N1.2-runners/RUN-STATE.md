# N1.2 run state

**Now:** built; converging, then verifier pass 1.

## History
- 2026-11-15 — spec and criteria written.
- 2026-11-15 — started; provider facts confirmed from docs and SDK types (D-31, D-32); runners, cost model, scheduler and `citewatch ask` built; real fixtures recorded with `scripts/record_provider_fixtures.py`. The first real calls found that `web_search_20260209` with dynamic filtering returns Claude answers with **no citations**, so the runner forces `allowed_callers: ["direct"]` (D-34, probe: 8 citations); `page_age` is relative ("198 days ago", D-35); OpenAI appends `utm_source=openai` (D-36). Spend: $0.45 in all (fixtures twice, one probe, one wasted re-record when an edit did not apply), in `studies/uk-health/data/spend-ledger.jsonl` (L-26).
