# N1.3 — Store, ledger and CLI skeleton

**Wave 1. Depends on:** N1.1. **Unblocks:** A2.2, A2.4, and through them the fetcher and every paid command.

## Goal
Every raw provider response and fetch record lands once, atomically, in a content-addressed store that a later stage can always rebuild from (D-1, D-2), and every command a user types has its final shape, flags and exit codes before any paid code exists (Tech Spec §3.1, §5).

## Outputs (`src/citewatch/store.py`, `ledger.py`, `cli.py`, `env.py`)
- `stage_key(stage, code_version, unit, config_hash, prompt_hash)` (sha256 over canonical JSON) and `RawStore(root)`: `put(stage, key, obj)` writes `<root>/data/raw/<stage>/<key[:2]>/<key>.json.gz` atomically, first writer wins (a lost race is not an error; EvalKit L-18); `get`; `has`; `keys(stage)` (STO-01). The root is the study folder (D-33).
- `Ledger(run_dir)`: one writer appending JSON lines to `run.log` (stage, key, cache_hit, latency_ms, cost_usd, error); every money value checked finite and non-negative (L-7) (STO-02).
- `citewatch` CLI with the §5 commands: `init`, `doctor`, `ask`, `extract`, `fetch`, `score`, `report`; `--json` on every command; `--dry-run` and `--max-cost` where §5 says; exit codes 0 done, 2 configuration or runtime error, 3 stopped at the cost cap, 4 judging pending. Commands whose node has not been built yet exit 2 with "not built yet (node X)", never a fake success (STO-03).
- `env.py`: `.env` loading without overriding real environment variables; a missing key names the exact variable; `doctor` reports which keys are set without printing any value, checks the user agent names a contact, checks `prices.yaml` age once it exists, and exits 2 when anything required is missing (STO-04).

## Rules
- Keys are stable under dict ordering and float formatting; the run number is part of every `ask` key so run 2 is never served from run 1.
- The store never holds page bodies; the storage audit (gate 9) runs over `data/`.
- `init` never overwrites an existing file.
- Unexpected exceptions exit 2 with a one-line message, never 1 (EvalKit L-29).

## Out of scope
Provider calls (N1.2), fetching (A2.2), metrics (M3.1), real `init` templates for other studies (B4.5 finishes them).
