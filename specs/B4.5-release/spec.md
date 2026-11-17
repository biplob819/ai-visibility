# B4.5 — Open-source packaging and v0.1.0

**Wave 4. Depends on:** B4.4. **Unblocks:** D5.3.

## Goal
`citewatch` 0.1.0 on PyPI, installable and usable by someone who has never seen the repo (D-23, D-24): an example report in under five minutes with no keys, a guide to running their own study, responsible-use rules that no setting can loosen, thresholds for CI (OWNER D-65), a public API under semver, and a release README with screenshots and every important link (OWNER D-58).

## Pieces
- Release: `.github/workflows/release.yml` (trusted publishing on a `v*` tag; the owner registers the pending publisher); `.github/workflows/published-smoke.yml` (after a release, `uvx citewatch@<version> --version` and `report --example` on Linux, macOS and Windows).
- Docs: `docs/quickstart.md`, `docs/own-study.md`, `docs/dates.md`, `docs/cost.md`, plus `docs/thresholds.md`, `docs/responsible-use.md`, `docs/versioning.md` (lane 2).
- Code (lane 2, D-77): thresholds; public API exports; politeness floor tests; community files.
- OSS-03 end to end: a custom one-provider study in another country on recorded fixtures (lane 5).
- Release README: screenshots of the dashboard, demo and CLI; a step-by-step guide; every link checked (`scripts/check_links.py`).
- Tag v0.1.0 (owner confirms) with the flagship results and changelog.
