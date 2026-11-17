# D5.2 run state

**Now:** built in lane 3 (merged 2256297); verifier pass 1 next; deploy waits on the owner.

## Log
- 2026-11-17 — lane 3 built the demo offline (fake providers, software authenticator with real P-256 signatures); design recorded as D-78.

## Known limits
- Not yet run in a real browser; Community Cloud may wrap the app in an iframe, which could affect WebAuthn (fallback: a v1 component in a popup).
- Upstash Lua scripting checked against a fake endpoint only.
