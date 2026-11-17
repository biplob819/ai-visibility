# D5.2 — Demo page and live mode

**Wave 5. Depends on:** D5.1, N1.2. **Unblocks:** D5.3.

## Goal
A public demo (US7, US8): look up any site's domain card without calling a model, browse the top ten by topic, and, behind passkey sign-in, ask one live question of both models and see their citations only (never answer prose, D-17), within a spend guard. Built in this repo's `demo/` (OWNER D-73), designed in D-78.

## Pieces
- `src/citewatch/demo/`: lookup, live, guard (per-request, hourly, daily caps), kv (Upstash REST, SQLite locally), passkeys (py_webauthn), component (WebAuthn element), logs (four fields), settings, make_code_hash.
- `demo/app.py` (Streamlit, three tabs), `demo/README.md` (deploy steps and secrets), `demo/requirements.txt`.
- Deploy to Streamlit Community Cloud: the owner creates the app and its secrets (DEM-04).

## Not in scope
The project page and video (D5.3).
