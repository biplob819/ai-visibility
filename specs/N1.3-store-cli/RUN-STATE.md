# N1.3 run state

**Now:** built; converging, then verifier pass 1.

## History
- 2026-11-15 — spec and criteria written.
- 2026-11-15 — started; tests first; `store.py` (content-addressed, atomic, first writer wins via `os.link`), `ledger.py`, `env.py`, Typer CLI with init/doctor and stubs that exit 2 naming their node; gate 10 smoke now covers --help, init and doctor (exit 2 without keys). Found while smoke-testing: without standalone mode Typer returns an Exit's code instead of raising it, so `main` ignored exit 2; fixed and tested.
