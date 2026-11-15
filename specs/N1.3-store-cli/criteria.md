# N1.3 acceptance criteria

**STO-01** `RawStore` keys are sha256 over canonical JSON and do not change with dict order; the run number changes an `ask` key; `put` is atomic and first-writer-wins under concurrent writers; `get` returns exactly what was put; nothing is written outside `data/raw/`.
**STO-02** `Ledger` appends one JSON line per event from a single writer, survives concurrent producers without interleaved lines, and rejects NaN, infinite or negative costs.
**STO-03** `citewatch --help` lists init, doctor, ask, extract, fetch, score and report; every command accepts `--json`; `ask` and `fetch` accept `--dry-run`, `ask` accepts `--max-cost`; unbuilt commands exit 2 naming their node; an unexpected exception exits 2 with one line, no traceback.
**STO-04** `.env` values load without overriding the real environment; `doctor` lists set and missing keys by name only, never their values, exits 2 when a required key or the user-agent contact is missing and 0 when everything is present; `init` creates a study folder and refuses to overwrite any existing file.
