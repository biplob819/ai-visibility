# N1.2 — Answer runners and cost model

**Wave 1. Depends on:** N1.1. **Unblocks:** A2.1, A2.4, D5.2.

## Goal
One runner per provider asks a question with the provider's native web search exactly as Tech Spec §7.1 specifies, stores the verbatim response before parsing anything, and prices it including search fees and search-result tokens, so every later number traces to a stored response and a known cost (D-2, OWNER D-8, OWNER D-19).

## Outputs (`src/citewatch/runners/`, `src/citewatch/cost.py`, `src/citewatch/prices.yaml`)
- `AnthropicRunner` (ASK-01): Messages API, tool `web_search_20260209` with `max_uses` and `user_location` from the study config, `output_config.effort`, no sampling parameters, no `fallbacks`; handles `end_turn`, `pause_turn` (continue up to 3 times), `refusal` (records `stop_details.category`) and `max_tokens`; server-tool error blocks recorded, never raised; search count from `usage.server_tool_use.web_search_requests`.
- `OpenAIRunner` (ASK-02): Responses API, tool `web_search` with `user_location`, `max_tool_calls`, `include=["web_search_call.action.sources"]`, `reasoning.effort`, the shared instruction as `instructions`; every `web_search_call` action recorded.
- One shared instruction string and its `prompt_hash` (ASK-03).
- Raw response stored through N1.3's `RawStore` before parsing; a resumed run calls only missing keys (ASK-04).
- Retry and error taxonomy of §3.4: transport, 429, 5xx and overloaded back off up to 6 attempts; refusals never retried and never rerouted (ASK-05).
- `prices.yaml` with `checked_on` and source per model; `answer_cost()` including per-search fees and search-result input tokens; `estimate_run()` printed before any paid call and aborting over `max_cost_usd`; spend appended to `docs/measurements/spend-ledger.jsonl` (ASK-06, L-7).
- Interleaved scheduling: both models per question concurrently, question order shuffled per run with a recorded seed; per-provider concurrency and rate limits (ASK-07).
- The Appendix C provider facts confirmed against live docs and recorded as decisions; test fixtures built from the SDKs' own response models (ASK-08, L-10).

## Rules
- No real API call in any test; recorded fixtures only. About $1 of live calls is allowed once, to record fixtures, after the owner confirms keys are set.
- A provider not configured (no key) is a configuration error naming the variable, not a transport failure (EvalKit L-21).

## Out of scope
Citation extraction (A2.1), the smoke run (A2.4).
