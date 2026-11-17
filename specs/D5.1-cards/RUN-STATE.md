# D5.1 run state

**Now:** verifier pass 2 fixes applied (D-71); focused pass 3 next.

## Log
- 2026-11-17 — built: 361 cards, `cited_instead`, improvement rows, `lookup()`; written by `citewatch score`.
- 2026-11-17 — verifier pass 1: CRD-01..03 and IMP-01 CONFIRMED (every count recomputed, zero mismatches; lookup 0.3 ms). IMP-02 partly DISPROVED: H1 robots wording false for 135 of 144 pages (robots.txt unreadable, not disallowing); M1 blocked/gated/not_html ignored; M2 page-age dates not counted as hidden; M3 stale not the §6.3 population; M4 intent_absent named the wrong publishers; M5 intent_absent unfair to narrow sites; lows (owner contradiction, junk lookups, source files, grammar, weak flagship test). Fixed per D-69; the flagship test now recomputes every page-based code.

- 2026-11-17 — verifier pass 2: CRD-01..03, IMP-01 CONFIRMED (every code recomputed for 361 publishers, 0 mismatches; all 9 robots_blocked pages truly disallowed per protego). IMP-02 DISPROVED on wording: M-a hidden_date false for pages showing a published date (patient.info and 4 more); M-b robots_unreadable blamed bot protection for 5xx, no response and redirects, and doi.org's status came from the wrong host; lows (not_html claim, IDN display, public suffixes, grammar, per-origin robots). Fixed per D-71.

## Known limits
- Multi-organisation pseudo-publishers from `publisher_of` (uk.com, icb.nhs.uk, scot.nhs.uk, wales.nhs.uk) get one card each; their findings lump several organisations together (D-4).
- Stale is a page-level reading of §6.3; 19 stale pages are dated only by the search tool's page age.
