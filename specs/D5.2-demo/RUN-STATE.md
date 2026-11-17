# D5.2 run state

**Now:** verifier pass 1 fixes merged (D-79); focused pass 2 next; deploy waits on the owner.

## Log
- 2026-11-17 — lane 3 built the demo offline (fake providers, software authenticator with real P-256 signatures); design recorded as D-78.

- 2026-11-17 — verifier pass 1 (security): DEM-01, 02, 03, 05 CONFIRMED (passkey attacks refused; 60-way registration burst held at 10 compares; BYOK keys absent from logs, KV, page, env; caps hold under concurrency); 15 of 19 mutants killed. Findings: M no proof that a blank visitor key never falls back to the owner's; L-M markdown injection through quoted spans; lows (store errors as tracebacks, window-boundary lockout, single use only on the page, crash-hold untested, 8-digit codes, prefix origin check, inflated lookup logs). Fixed per D-79.

## Known limits
- Not yet run in a real browser; Community Cloud may wrap the app in an iframe, which could affect WebAuthn (fallback: a v1 component in a popup).
- Upstash Lua scripting checked against a fake endpoint only.
