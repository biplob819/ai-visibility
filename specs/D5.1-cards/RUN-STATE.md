# D5.1 run state

**Now:** GREEN (verifier pass 5, 2026-11-17).

## Log
- 2026-11-17 — built: 361 cards, `cited_instead`, improvement rows, `lookup()`; written by `citewatch score`.
- 2026-11-17 — verifier pass 1: CRD-01..03 and IMP-01 CONFIRMED (every count recomputed, zero mismatches; lookup 0.3 ms). IMP-02 partly DISPROVED: H1 robots wording false for 135 of 144 pages (robots.txt unreadable, not disallowing); M1 blocked/gated/not_html ignored; M2 page-age dates not counted as hidden; M3 stale not the §6.3 population; M4 intent_absent named the wrong publishers; M5 intent_absent unfair to narrow sites; lows (owner contradiction, junk lookups, source files, grammar, weak flagship test). Fixed per D-69; the flagship test now recomputes every page-based code.

- 2026-11-17 — verifier pass 2: CRD-01..03, IMP-01 CONFIRMED (every code recomputed for 361 publishers, 0 mismatches; all 9 robots_blocked pages truly disallowed per protego). IMP-02 DISPROVED on wording: M-a hidden_date false for pages showing a published date (patient.info and 4 more); M-b robots_unreadable blamed bot protection for 5xx, no response and redirects, and doi.org's status came from the wrong host; lows (not_html claim, IDN display, public suffixes, grammar, per-origin robots). Fixed per D-71.

- 2026-11-17 — verifier pass 3 (focused): every D-71 item FIXED; hidden_date, robots_blocked (9) and robots_unreadable (135) recomputed for every publisher, 0 mismatches; lookup edge cases pass; CRD-01..03, IMP-01 CONFIRMED. IMP-02 DISPROVED on wording: M hidden_date stated pages show no date (an extraction miss stated as fact; england.nhs.uk, blog.gov.uk); L-M the redirect fix blamed sites for citewatch's own policy; L doi.org fix misdirected, singular phrasing. Fixed per D-72.

- 2026-11-17 — verifier pass 4 (focused): items 1, 2 and 5 PASS (47 hidden_date rows hedged; all 54 robots rows' fixes match their causes; counts unchanged, byte-identical). IMP-02 DISPROVED narrowly: M 34 rows put citewatch's stricter-than-RFC 401/403 rule on the publisher; L doi.org plural. Fixed per D-75.

- 2026-11-17 — verifier pass 5 (focused): all four items PASS; every robots_unreadable row attributes the outcome to citewatch's rule, says stricter than RFC 9309 exactly for status < 500, host/hosts and it/them correct; counts unchanged and byte-identical. IMP-02 CONFIRMED. OPEN HIGH/MEDIUM: 0 (D-26 met). Rows flipped green.

## Known limits
- Multi-organisation pseudo-publishers from `publisher_of` (uk.com, icb.nhs.uk, scot.nhs.uk, wales.nhs.uk) get one card each; their findings lump several organisations together (D-4).
- Stale is a page-level reading of §6.3; 19 stale pages are dated only by the search tool's page age.
- `tests/runners/test_schedule.py::test_a_worker_bug_stops_queued_calls` failed once under `-x` (timing); passes alone. Logged for hardening, outside D5.1.
