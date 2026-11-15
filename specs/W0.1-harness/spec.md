# W0.1 — Repo and harness

**Wave 0. Depends on:** —. **Unblocks:** N1.1 and everything after it.

## Goal
A uv project for the `citewatch` package and the lean Kova build harness ported from EvalKit, so every later node is dependency-gated, proven by named tests, and checked by 12 gates that are each shown to fail (Tech Spec §12).

## Outputs
- `pyproject.toml` (distribution `citewatch`, import and CLI `citewatch`, src layout, Python ≥3.11, hatchling; OWNER D-23), MIT `LICENSE`, `.gitattributes` forcing LF, `.gitignore`, ruff pre-commit (HAR-01).
- `.github/workflows/ci.yml`: ruff, ruff format, pyright, pytest (all markers including golden), secret scan, storage audit, graph eligibility, `uv build`, on Python 3.11–3.13 × Linux, macOS and Windows, on push and PR, `contents: read` only (HAR-02).
- `scripts/harness_lib.py`, `verify_graph_eligibility.py`, `node_start.py` ported from EvalKit with node ids `[WNAMSBD]n.n` (HAR-03).
- `scripts/node_converge.py` with the gate list of Tech Spec §12.6: gate 7 golden, gate 8 politeness (`pytest -m polite` plus `scripts/fetch_audit.py` over committed fetch logs), gate 9 safety (`pytest -m safety`, secret scan, `scripts/storage_audit.py`), gate 10 build with the smoke commands that exist so far (HAR-04).
- `docs/graph/graph.md` and `catalog.tsv` generated from Tech Spec §12.2 and §12.4; `docs/decisions.md` (D-1 to D-25); `docs/lessons.md` (L-1 to L-12 inherited, §12.8); `changelog.md`; `scripts/status.py` (HAR-05).
- `scripts/secret_scan.py` (ported) and `scripts/storage_audit.py` (new) (HAR-06).
- `docs/harness/verifier-prompt.md` (HAR-07).

## Rules
- `fetch_audit.py` reads JSONL lines (plain or gzipped) with `url, host, at (ISO 8601 with zone), attempt, status, bytes, robots ("allowed"|"disallowed"), outcome, user_agent` (Tech Spec §7.2), checks every field's type, and applies the rules to all logs together: two requests to one host (case, port and trailing dot ignored) less than 1.0 s apart; a request to a URL whose robots decision was `disallowed` (robots.txt itself exempt); a request for a URL after robots refused it, or after it returned 401, 403 or 451; more than three requests for one page (counted, not trusted from `attempt`); more than one user agent; a `robots_disallowed` line with a status or bytes. Pages are compared with scheme, host case, port, trailing slash, fragment and query order normalised. No logs is SKIP, never PASS.
- `storage_audit.py` scans every tracked or untracked-but-not-ignored file under `data/` and `results/`, decompressing gzip, bzip2, xz and zip by magic bytes (nested up to three layers), and fails on HTML document markers (`<!doctype html`, `<html`, `<body`, also JSON- or HTML-escaped) or on `body`, `html` or `page_text` as a JSON or repr key (also double-encoded), a YAML key, or a CSV/TSV header column (any case). It also fails when the body cache folder (`~/.cache/citewatch/bodies/`, overridable by `CITEWATCH_BODY_CACHE`) is non-empty while node M3.2 is not building.
- The secret scan lists files NUL-separated (no quoted names skipped) and unpacks compressed files before scanning.
- The catalog is read and written without CSV quoting, so proof cells round-trip byte for byte; the writer refuses any cell it could not read back.
- Gate 10 runs its smoke commands with every provider credential removed from the environment and checks each command's expected exit code.
- Gate 11 counts only real test files (`tests/**/test_*.py`, `*_test.py`, `conftest.py`) that still exist; fixtures and deleted tests do not count.
- Gate 3 treats a proof as skipped when pytest would skip or never collect it: skip/skipif/xfail marks by any import or alias, unittest skips, parametrized cases marked skip, module-level skip or importorskip, runtime skips (including `skipTest`, `raise SkipTest`, `raise pytest.skip.Exception`), `__test__ = False`, and `Test*` classes with `__init__`.
- Every gate keeps EvalKit's rules: reported even after a failure; a tool error is a FAIL; self-tests name the planted defect.

## Out of scope
Application code (from N1.1). Remote repo creation and push (owner approval, B4.4).
