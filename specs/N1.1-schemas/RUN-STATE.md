# N1.1 run state

**Now:** pass 1 fixes in; converging, then verifier pass 2.

## History
- 2026-11-15 — spec and criteria written.
- 2026-11-15 — started after W0.1 green; tests first; schemas in `src/citewatch/schemas/` (base adapted from EvalKit), flagship `studies/uk-health/study.yaml`, ten v1 fixtures; summary row schemas and `reviewed_source` added to Tech Spec §4 so spec and code match.
- 2026-11-15 — verifier pass 1 CONFIRMED SCH-02/03/04; DISPROVED SCH-01 (upper-case scheme accepted: `urlsplit` lower-cases it) and SCH-05 (`UK`/`ZZ` accepted as countries; `https://` with no host counted as a contact). Medium: weak user agent (could pose as a browser), `FrozenDict` not picklable or deep-copyable, `ts_reason` fixed to the UK rubric. 92 mutants, 28 surviving test gaps. Fixed: raw scheme checked; ISO 3166-1 list with hints; user agent must start `citewatch/<version>`, name a URL with a host or an email, and hold no control characters; `FrozenDict` pickles and deep-copies; `ts_reasons` per study (flagship lists five); transport errors carry no raw key; timestamps must be UTC; strict floats; abbreviations no longer split quotes; citation refs, publisher-vs-host, user info and hand-label date order checked; BOM-tolerant loaders; every surviving mutant pinned (L-23, L-24).

## Known limits (D-26, low) — each with the test that would close it
- `FrozenDict` can still be mutated through `dict.__setitem__(d, k, v)` and pydantic's `model_copy(update=...)` skips validation; both are deliberate bypasses no stage uses. Closing test: an AST scan forbidding `dict.__setitem__` and `model_copy(update=` in `src/` (not written).
- Question ids follow `^[a-z][a-z0-9]*-\d{3,}$` and intents are snake_case slugs, narrower than §4's `str`; the error names the pattern. Closing test: `test_bad_questions_are_rejected` extended if a user study needs other ids (documented in B4.5's run-your-own-study guide).
- A quote like "First.Second.Third." (no spaces) passes the one-sentence rule; the 300-character cap still bounds storage. Closing test: M3.2 trims quotes to one sentence before storing.
