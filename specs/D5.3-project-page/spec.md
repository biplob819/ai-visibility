# D5.3 — Project page, walkthrough GIF, supporting notes

**Wave 5. Depends on:** B4.5, D5.2. **Unblocks:** nothing (last node).

## Goal
The portfolio's project page can be built from this repository alone: a case study that states the finding with its counts and links every artefact, a silent walkthrough GIF of the real screens (OWNER D-86, in place of a video), and the how-I-built-it note and one-page PRD. Wording approved by the owner (OWNER D-85); the portfolio-site session owns the site and pulls `portfolio.yml` and `docs/case-study.md`.

## Pieces
- `docs/case-study.md`: narrative, My role, Key decisions, Links (repository, dashboard, post, signal spec, demo).
- `portfolio.yml`: title, slug, summary, links (incl. demo), images (incl. walkthrough and demo), tech, status.
- `docs/assets/walkthrough.gif` and its shot list `docs/walkthrough.md`.
- `docs/how-i-built-it.md`, `docs/prd-one-page.md`.
- Tests: `tests/test_project_page.py` pins the links, every figure against `summary.json`, the GIF's format and the notes.
