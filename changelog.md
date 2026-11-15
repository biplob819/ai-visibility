# Changelog

Format: `[TYPE] [NODE] — summary`. Newest first.

- [GREEN] [A2.2] — verified over nine skeptical passes (L-32, L-33; D-42); robots verdict equals protego's on the path actually sent, wire spacing ≥1 s, no markup stored, audits clean on fuzzed multi-run logs
- [GREEN] [A2.1] — verified over three skeptical passes (D-43); only current answers extracted, every row field pinned with literal values
- [FEAT] [A2.1] — citation extraction for both providers from API citation fields only, consulted sources with page_age, `canonical_url` (idempotent, utm and click IDs stripped), `publisher_of` per D-4 offline, `citewatch extract`
- [GREEN] [N1.2] — verified over six skeptical passes (L-27, L-29 to L-31; D-37 to D-41); money recorded for every paid call under errors, interrupts and signals
- [FEAT] [A2.2] — polite fetcher: protego robots per origin kept for the study, 1 req/s per host and 8 in flight, hand-followed redirects re-checking robots, retries and page history that keep gate 8's rules across runs, HTML-only capped bodies held in memory, gating, fetch log, `citewatch fetch` with `--dry-run`
- [GREEN] [N1.3] — verified over four skeptical passes (L-28); CI green on all three systems
- [FEAT] [N1.2] — Claude and OpenAI runners with native web search, cost model, scheduler, `citewatch ask` (dry run, cap, resume), real fixtures
- [FEAT] [N1.3] — raw store, run ledger, .env loading and the citewatch CLI (init, doctor; other commands exit 2 naming their node)
- [GREEN] [N1.1] — verified over two skeptical passes (L-23, L-24); 299 tests
- [FEAT] [N1.1] — results format v1 schemas, study config and question loader, flagship study.yaml
- [GREEN] [W0.1] — verified over six skeptical passes (L-14 to L-22, D-26); 153 tests; CI green on Python 3.11–3.13 × Linux, macOS, Windows
- [FEAT] [W0.1] — repo, uv project and the lean Kova build harness ported from EvalKit (12 gates, politeness and storage gates new)
