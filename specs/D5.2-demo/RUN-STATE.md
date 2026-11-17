# D5.2 run state

**Now:** DEM-01, 02, 03, 05 confirmed (pass 2); DEM-04 waits on the owner's deploy, then the live check.

## Log
- 2026-11-17 — lane 3 built the demo offline (fake providers, software authenticator with real P-256 signatures); design recorded as D-78.

- 2026-11-17 — verifier pass 1 (security): DEM-01, 02, 03, 05 CONFIRMED (passkey attacks refused; 60-way registration burst held at 10 compares; BYOK keys absent from logs, KV, page, env; caps hold under concurrency); 15 of 19 mutants killed. Findings: M no proof that a blank visitor key never falls back to the owner's; L-M markdown injection through quoted spans; lows (store errors as tracebacks, window-boundary lockout, single use only on the page, crash-hold untested, 8-digit codes, prefix origin check, inflated lookup logs). Fixed per D-79.

- 2026-11-17 — verifier pass 2 (focused): every D-79 fix HOLDS (20 injection payloads rendered inert; ≤10 code checks in any 60 minutes under bursts; pending single use; crash keeps the hold; exact origin); pass-1 attacks still refused; 16 of 20 mutants killed. DEM-01, 02, 03, 05 CONFIRMED; no high or medium finding.

## Known limits
- Not yet run in a real browser; Community Cloud may wrap the app in an iframe, which could affect WebAuthn (fallback: a v1 component in a popup).
- Upstash Lua scripting checked against a fake endpoint only.
- Test gaps (low): Streamlit-only syntax inertness, `link()` with a javascript: URL (citation URLs are already canonicalised), the generic except in `finish()`, and settle's store-error except are not pinned by tests.
- Anyone can keep registration locked by steady guessing (sign-in unaffected; reset documented).
- An origin configured with an explicit default port (`:443`) never matches what browsers send; configure the origin without it.
