# D5.1 run state

**Now:** verifier pass 1 fixes applied (D-69); pass 2 next.

## Log
- 2026-11-17 — built: 361 cards, `cited_instead`, improvement rows, `lookup()`; written by `citewatch score`.
- 2026-11-17 — verifier pass 1: CRD-01..03 and IMP-01 CONFIRMED (every count recomputed, zero mismatches; lookup 0.3 ms). IMP-02 partly DISPROVED: H1 robots wording false for 135 of 144 pages (robots.txt unreadable, not disallowing); M1 blocked/gated/not_html ignored; M2 page-age dates not counted as hidden; M3 stale not the §6.3 population; M4 intent_absent named the wrong publishers; M5 intent_absent unfair to narrow sites; lows (owner contradiction, junk lookups, source files, grammar, weak flagship test). Fixed per D-69; the flagship test now recomputes every page-based code.

## Known limits
