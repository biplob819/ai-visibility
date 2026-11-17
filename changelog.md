# Changelog

Format: `[TYPE] [NODE] — summary`. Newest first.

- [FEAT] [S3.1] — study runs 1 and 2 ($15.03, 400 answers, 0 errors), spend reconciled exactly, run data frozen by hash (RUN-04)
- [GREEN] [M3.3] — verified over three passes (D-67, D-68); held-out rule over distinct sampled pages; checker load failures counted, never scored; 67% within 7 days (18/27)
- [GREEN] [M3.2] — verified over three passes (D-67, D-68); support rates per model and judge, owner labels, EvalKit calibration, gaps; body cache finalised
- [FEAT] [M3.3] — held-out date check on 55 pages, agent-checked and owner-approved (OWNER D-63, D-64): 67% within 7 days (18/27 judgeable, Wilson 48–81%); label freeze tests
- [FEAT] [M3.2] — support judging with EvalKit (two judges, OWNER D-60, D-61), owner labels (OWNER D-62), judge calibration with EvalKit's cluster kappa (OWNER D-65), body cache finalised
- [GREEN] [M3.1] — verified over three passes (D-55, D-56); §6 metrics with the question-cluster bootstrap, Holm and Wilson; `citewatch score` writes summary.json; DuckDB views
- [GREEN] [A2.4] — paid smoke run 0 ($0.79), measured cost model, parity report, golden replay
- [GREEN] [N1.4] — 100 owner-approved questions frozen with the pre-registration and data card (OWNER D-47, D-51)
- [GREEN] [A2.3] — verified over five skeptical passes (D-44, D-45); 21-page real test set confirmed by the owner (OWNER D-46)
- [FEAT] [A2.3] — date resolver: candidates from the seven §7.3 sources, plausibility rules, precedence, sitemaps from robots.txt, `page_meta.jsonl` from `citewatch fetch`; 21-page real test set with drafted labels awaiting the owner (DAT-04)
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
