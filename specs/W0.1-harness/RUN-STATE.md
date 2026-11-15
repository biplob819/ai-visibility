# W0.1 run state

**Now:** verifier pass 1 fixes in; converging, then verifier pass 2.

## History
- 2026-11-15 — records generated from the Tech Spec (20 nodes, 96 capabilities, D-1 to D-20).
- 2026-11-15 — built; first commit pushed to the public repo; CI green.
- 2026-11-15 — OWNER D-23/D-24: open-source tool `citewatch`; package renamed; Python 3.11–3.13 × three OS; node B4.5 added (21 nodes, 104 capabilities).
- 2026-11-15 — verifier pass 1 disproved HAR-04 (self-tests for gates 10 and 12 passed with the gate broken or the tool missing; only one politeness rule planted through gate 8) and HAR-06 (secret scan skipped names git quotes; storage audit missed `.GZ`), plus 12 should-fix items: robots and status values unchecked, retry rule dodged by URL form, rules per file only, robots.txt exemption missing, skipped lines hiding requests, `.gz` not secret-scanned, renamed or escaped bodies missed, gate 3 accepting module/class/runtime skips and xfail, catalog quoting breaking proof cells, CI on main only. All fixed with regressions in `tests/harness/test_verifier_regressions.py` and stronger self-tests (L-14, L-15).
