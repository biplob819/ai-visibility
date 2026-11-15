# A2.1 run state

**Now:** built and converged; verifier pass 1.

## History
- 2026-11-15 — spec and criteria written; started after N1.2 green. Real OpenAI responses put inline markdown citation links inside the answer text, spanned by the annotation indices (D-43).
- 2026-11-15 — built `src/citewatch/extract/` and `citewatch extract`; 42 tests on the recorded fixtures, with hypothesis property tests (idempotence found `+` and `%2541` round-trip bugs, both fixed). tldextract on its bundled PSL snapshot, no network.

## Known limits
