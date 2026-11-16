# A2.4 acceptance criteria

**SMK-01** Run 0 asked the 10 questions on both models for real; 20 answers stored raw; every paid call is in the spend ledger; total under the `--max-cost` cap.
**SMK-02** Measured mean input and output tokens, searches and cost per answer per model are written into the cost model (`prices.yaml` or a measured-averages file the estimator reads); the full study estimate is reprinted from them; if a study run would exceed $25 the owner is asked (OWNER D-19).
**SMK-03** `extract`, `fetch` and dates ran on the smoke data with no crash; each surprise is logged as a lesson or a fix with a test.
**SMK-04** A parity report records per model: GB location sent, searches per answer (at most 3), word counts and over-length rate, refusals, errors and citation counts.
**SMK-05** A golden fixture under `tests/fixtures/golden/` holds the smoke responses (or a slice), the recorded HTTP responses the fetch made, and the outputs they produce; a CI test replays it offline and gets byte-identical outputs.
