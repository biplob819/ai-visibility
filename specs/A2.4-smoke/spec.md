# A2.4 — Smoke run

**Wave 2. Depends on:** N1.2, N1.3, N1.4, A2.1, A2.3. **Unblocks:** S3.1.

## Goal
Run the whole pipeline once for real on a small slice before the study runs, so design errors surface cheaply (EvalKit L-37), the cost model is measured rather than guessed (H11), and a golden fixture exists for CI replay (§11).

## Scope
- Run 0: 10 frozen questions, 2 per intent (one time-sensitive, one not), chosen with `random.Random(20261115)`: `v-012,v-002,v-037,v-023,v-053,v-043,v-078,v-064,v-092,v-081`.
- Both models, web search on, as the study runs will. Approved by the owner (OWNER D-48, about $2); `--max-cost 5`.
- Then `extract`, `fetch` and the date pipeline on the smoke data.
- Outputs: measured averages written into the cost model and a reprinted full-run estimate; a parity report; a golden fixture (smoke responses plus recorded HTTP responses and the outputs they produce); lessons for every surprise.

## Out of scope
Metrics (M3.1), the support check (M3.2), study runs (S3.1).
