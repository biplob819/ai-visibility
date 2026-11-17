# B4.4 — Public repo

**Wave 4. Depends on:** B4.2, B4.3. **Unblocks:** B4.5.

## Goal
The repository reads as a finished, honest study (US5, US6): a README with the finding, method, how to rerun it and what it costs; the licence and data card; the decisions, the pre-registration and every deviation from it published; and an audit showing no secret, `.env`, page body or job-search content anywhere in its history (OWNER D-21, D-22).

## Pieces
- `README.md`: finding with counts and intervals (from `summary.json`), links to the dashboard, post, signal spec, data card, pre-registration, decisions and deviations; method in brief; rerun steps; cost; licence.
- `docs/deviations.md`: each change from the frozen pre-registration (§6) and plan, with its decision id and effect on results.
- `scripts/history_audit.py`: every file version in history checked (secrets, `.env`, page bodies, job-search markers).
- Screenshots of the dashboard and post in `docs/assets/screenshots/`.
- Architecture diagram and PRD brought in line with D-70 (GitHub Pages) and D-73 (demo in this repo).

## Not in scope
Packaging, PyPI and the release README's full guide (B4.5, OSS-09).
