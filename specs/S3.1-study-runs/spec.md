# S3.1 — Study runs 1 and 2

**Wave 3. Depends on:** A2.4. **Unblocks:** B4.1, B4.3.

## Goal
Collect the two study runs under Tech Spec §13: gate G1 before run 1, gate G2 before run 2, audits after each, a manifest per run, spend reconciled, data committed and frozen.

## Order
- Gate G1 (enforced by `citewatch ask --run 1`; `--dry-run` shows it).
- Run 1: `ask --run 1` → `extract` → support sample drawn (M3.2's sampler) → `fetch` → audits.
- Gate G2 (enforced by `ask --run 2`): no change to runner, extractor, prompt, questions or `study.yaml` since run 1's commit; at least 2 hours after run 1 finished.
- Run 2: `ask --run 2` → `extract` → `fetch` (new URLs only) → audits.
- Freeze: manifests, data committed, `score`, labels imported, `score --finalise` (M3.2, M3.3).

Approved by the owner: about $38 for both runs (OWNER D-48); measured estimate about $12 a run (D-54).
