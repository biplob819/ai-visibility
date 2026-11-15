# N1.3 run state

**Now:** pass 1 fixes in; converging, then verifier pass 2.

## History
- 2026-11-15 — spec and criteria written.
- 2026-11-15 — started; tests first; `store.py` (content-addressed, atomic, first writer wins via `os.link`), `ledger.py`, `env.py`, Typer CLI with init/doctor and stubs that exit 2 naming their node; gate 10 smoke now covers --help, init and doctor (exit 2 without keys). Found while smoke-testing: without standalone mode Typer returns an Exit's code instead of raising it, so `main` ignored exit 2; fixed and tested.
- 2026-11-15 — verifier pass 1 CONFIRMED STO-01/02/04 (16-process store races, SIGKILL mid-write, 8-process ledger appends all clean); DISPROVED STO-03 (`typer>=0.12` allowed versions without `TyperException`: exit 1 with a traceback, or a fake exit 0 on 0.12). Medium: the init template's `example.org` contact passed doctor (D-25); no test proved `put` atomic. Fixed: `typer>=0.28`; placeholder contacts (example.org/.com/.net, localhost, .test/.example/.invalid) refused; `init --contact`; tests for a failed mid-write and a concurrent reader; init refuses dangling symlinks and creates exclusively; ledger extras cannot replace reserved fields or smuggle bad money; gate 10 smokes a usage error (exit 2) and `ask --dry-run`.

## Known limits (D-26, low) — each with the test that would close it
- A crash can leave `.tmp-*` files in the store; `keys()` ignores them. Closing test: a `citewatch doctor` check that lists and offers to remove stale temp files (not written).
- No fallback where hard links are unsupported (exFAT, some network shares): `put` raises there. Closing test: a store test on a filesystem without `link` (not available in CI).
- `1` and `1.0` give different store keys; units are built by code, never typed by people. Closing test: `test_keys_are_stable_under_dict_order...` extended if a caller ever builds keys from parsed JSON numbers.
- Usage errors print plain text even with `--json`. Closing test: a `--json` usage-error case in `test_cli.py` (not written).
- `Ledger.rows()` raises on a torn line (one writer per run makes this unlikely). Closing test: a torn-line fixture in `test_ledger.py` (not written).
