# B4.3 run state

**Now:** GREEN (verifier pass 2, 2026-11-17).

## Log

- 2026-11-17 — verifier pass 1: SIG-01 and SIG-02 CONFIRMED on structure (one A4 page; PDF text equals the HTML; every number traced). Findings fixed per D-75: M-H stale wording dropped "dated"; M overclaims (scheduled re-runs, thresholds, CSV, lookup); M the tests did not check A4 or that the PDF is the current HTML; L hard-coded counts, top-10 caveat, citation weight undefined.

- 2026-11-17 — verifier pass 2 (focused): SIG-01, SIG-02 CONFIRMED (one A4 page; PDF text equals the HTML; stamp ties PDF to build; stale-PDF and Letter-size mutations caught; every number traced). Lows: the Limits line was hard-coded (now derived); the trace test matches any equal Interval (the builder looks rows up by key). OPEN HIGH/MEDIUM: 0 (D-26 met). Rows flipped green.

## Known limits
- The number-trace test accepts any summary Interval with equal values; the builder selects rows by publisher, model and run.
