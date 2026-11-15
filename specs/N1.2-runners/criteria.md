# N1.2 acceptance criteria

**ASK-01** The Anthropic request carries `web_search_20260209` with `max_uses`, the study's `user_location`, the effort level, no sampling parameters and no `fallbacks`; `pause_turn` is continued at most 3 times; a refusal is recorded with its category and never retried; a server-tool error block is recorded, not raised; the search count comes from `usage.server_tool_use`.
**ASK-02** The OpenAI request carries `web_search` with the study's `user_location`, `max_tool_calls`, `include=["web_search_call.action.sources"]`, the reasoning effort and the shared instruction; every web search action in the response is recorded.
**ASK-03** Both runners send byte-identical instruction text, and `prompt_hash` changes when and only when it changes.
**ASK-04** The verbatim response is in the raw store before any parsing; rerunning a completed run makes no calls; an interrupted run calls only the missing keys.
**ASK-05** Transport, 429, 5xx and overloaded errors back off with jitter up to 6 attempts; schema-level and refusal outcomes are never retried; a missing key is a configuration error naming the variable.
**ASK-06** `answer_cost` matches a hand calculation for recorded fixtures including search fees and search-result tokens; `estimate_run` aborts before any call when over `max_cost_usd`; NaN, infinite or negative money values are errors; every paid call is appended to the spend ledger.
**ASK-07** For each question both models are asked concurrently; question order is a seeded shuffle recorded in the run manifest; per-provider concurrency limits hold under load.
**ASK-08** Each Appendix C fact is recorded in `decisions.md` with its source and date; fixtures are built from the SDK response models.
