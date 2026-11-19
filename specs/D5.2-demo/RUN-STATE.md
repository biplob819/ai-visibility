# D5.2 run state

**Now:** green. DEM-01..05 confirmed; DEM-04 by the live check on the deployed app (OWNER D-88).

## Log
- 2026-11-17 — lane 3 built the demo offline (fake providers, software authenticator with real P-256 signatures); design recorded as D-78.

- 2026-11-17 — verifier pass 1 (security): DEM-01, 02, 03, 05 CONFIRMED (passkey attacks refused; 60-way registration burst held at 10 compares; BYOK keys absent from logs, KV, page, env; caps hold under concurrency); 15 of 19 mutants killed. Findings: M no proof that a blank visitor key never falls back to the owner's; L-M markdown injection through quoted spans; lows (store errors as tracebacks, window-boundary lockout, single use only on the page, crash-hold untested, 8-digit codes, prefix origin check, inflated lookup logs). Fixed per D-79.

- 2026-11-17 — verifier pass 2 (focused): every D-79 fix HOLDS (20 injection payloads rendered inert; ≤10 code checks in any 60 minutes under bursts; pending single use; crash keeps the hold; exact origin); pass-1 attacks still refused; 16 of 20 mutants killed. DEM-01, 02, 03, 05 CONFIRMED; no high or medium finding.

- 2026-11-19 — live check on https://citewatch.streamlit.app (owner's browser): lookup of nhs.uk matches summary.json (10/100 Claude run 1, 83/100 GPT run 1); live mode off with a clear message while two secrets were misnamed, on after the fix; registration code checked (a wrong code refused), passkey registered with the platform authenticator inside Community Cloud's same-origin iframe, sign-in works; one live question on the visitor's OpenAI key: 1 citation (nhs.uk), no quote (provider gives none), no answer text, cost $0.035, no error text; the blank Anthropic field made no call and did not fall back to owner keys (none are configured). Claude's live path not exercised (OWNER D-88).

## Known limits
- Claude's live path is checked against offline fakes only (OWNER D-88).
- Upstash Lua scripting checked against a fake endpoint only.
- Test gaps (low): Streamlit-only syntax inertness, `link()` with a javascript: URL (citation URLs are already canonicalised), the generic except in `finish()`, and settle's store-error except are not pinned by tests.
- Anyone can keep registration locked by steady guessing (sign-in unaffected; reset documented).
- An origin configured with an explicit default port (`:443`) never matches what browsers send; configure the origin without it.
