# W0.1 — Repo and harness

**Wave 0. Depends on:** —. **Unblocks:** N1.1 and everything after it.

## Goal
A uv project for the `visibility` package and the lean Kova build harness ported from EvalKit, so every later node is dependency-gated, proven by named tests, and checked by 12 gates that are each shown to fail (Tech Spec §12).

## Outputs
- `pyproject.toml` (distribution `ai-visibility`, import and CLI `visibility`, src layout, Python 3.12, hatchling), MIT `LICENSE`, `.gitattributes` forcing LF, `.gitignore`, ruff pre-commit (HAR-01).
- `.github/workflows/ci.yml`: ruff, ruff format, pyright, pytest (all markers including golden), secret scan, storage audit, graph eligibility, `uv build`, on Linux and macOS, on push and PR, `contents: read` only (HAR-02).
- `scripts/harness_lib.py`, `verify_graph_eligibility.py`, `node_start.py` ported from EvalKit with node ids `[WNAMSBD]n.n` (HAR-03).
- `scripts/node_converge.py` with the gate list of Tech Spec §12.6: gate 7 golden (one interpreter, D-18), gate 8 politeness (`pytest -m polite` plus `scripts/fetch_audit.py` over committed fetch logs), gate 9 safety (`pytest -m safety`, secret scan, `scripts/storage_audit.py`), gate 10 build with the smoke commands that exist so far (HAR-04).
- `docs/graph/graph.md` and `catalog.tsv` generated from Tech Spec §12.2 and §12.4; `docs/decisions.md` (D-1 to D-20); `docs/lessons.md` (L-1 to L-12 inherited, §12.8); `changelog.md`; `scripts/status.py` (HAR-05).
- `scripts/secret_scan.py` (ported) and `scripts/storage_audit.py` (new) (HAR-06).
- `docs/harness/verifier-prompt.md` (HAR-07).

## Rules
- `fetch_audit.py` reads JSONL lines with `url, host, at (ISO 8601), attempt, status, robots ("allowed"|"disallowed"), outcome, user_agent` (Tech Spec §7.2). It fails on: two requests to one host less than 1.0 s apart; any request to a URL whose robots decision was `disallowed` (a robots.txt request itself is exempt); any retry of a URL after a 401, 403 or 451; more than one distinct user agent; an unparseable line. No logs is SKIP, never PASS.
- `storage_audit.py` scans every tracked or untracked-but-not-ignored file under `data/` and `results/` (decompressing `.gz`) and fails on HTML document markers (`<!doctype html`, `<html`, `<body`) or on JSON keys named `body`, `html` or `page_text`. It also fails when the body cache folder (`~/.cache/ai-visibility/bodies/`, overridable by `VISIBILITY_BODY_CACHE`) is non-empty while node M3.2 is not `building`.
- Every gate keeps EvalKit's rules: reported even after a failure; a tool error is a FAIL; self-tests name the planted defect.

## Out of scope
Application code (from N1.1). Remote repo creation and push (owner approval, B4.4).
