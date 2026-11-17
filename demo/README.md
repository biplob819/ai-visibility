# citewatch demo

A Streamlit page over the UK health study (Tech Spec §9, OWNER D-73).

- **Look up a site** (the default): type a domain or URL. You get its share of answers by model and run, how fresh its cited pages were, who was cited instead, and improvement rows with fixes. A site that was never cited gets "not cited in any of the 400 answers", plus the most-cited publishers for the topic you pick. This mode reads `studies/uk-health/results/domain_cards.json` and never calls a model.
- **Top ten by topic**: the ten publishers cited in the most answers for each intent.
- **Live question**: needs a passkey. One question goes to both models with the study's §7.1 settings. The page shows each model's citations (URL, publisher, quoted span) and never the answer text (D-17).

All the logic lives in `src/citewatch/demo/`. `demo/app.py` only lays out the page.

## How live mode is protected

| Control | Where | Rule |
| --- | --- | --- |
| Passkey sign-in (WebAuthn) | `citewatch.demo.passkeys`, `citewatch.demo.component` | Live mode needs a registered passkey. Sign-in is by passkey alone (OWNER D-58, D-59) |
| Registration code | `RegistrationGate` | Registering a passkey needs the owner's numeric code of 12 to 32 digits. The code is checked against a salted PBKDF2 hash of at least 600,000 rounds (a weaker stored hash is refused) with a constant-time compare. Attempts are limited to 3 per session and 10 across all visitors in any hour: each attempt counts against the current and the previous clock hour together, so no burst can straddle the hour. The limit is counted before the compare, so refused attempts count too |
| Per-request cap | `SpendGuard.check_cap` | $0.50 per question, whoever's keys are used |
| Rate limit | `SpendGuard` | 5 live questions per passkey per hour |
| Owner's daily cap | `SpendGuard.reserve` / `settle` | $3 a day. Only calls on the owner's keys count. The cap is held atomically in the KV, so concurrent requests cannot pass it together |
| Bring your own keys | `ProviderKeys`, `make_runners` | A signed-in visitor can paste their own Anthropic and OpenAI keys. The keys stay in that session's memory. They are never logged, stored or shown, and provider error messages are never echoed. A visitor who gives only one key gets that model only; the other shows `No openai key given.` (or `anthropic`) and the owner's key is never used in its place |
| Logs | `citewatch.demo.logs` | One line per request with four fields only: `at`, `mode`, `latency_ms`, `cost_usd`. No question, domain, IP address, passkey id or key. A lookup is logged once per distinct query and topic in a session, not on every rerun |
| Single-use ceremonies | `Pending`, `Passkeys` | Each sign-in or registration challenge can be finished once, pass or fail, so a captured response cannot be replayed, even from an authenticator whose signature counter stays at 0 |
| Exact origin | `exact_origin` | `CITEWATCH_DEMO_ORIGIN` must be exactly `https://<host>[:port]` at or under the RP ID; plain `http` is allowed only for `localhost` |
| No tracebacks | `demo/.streamlit/config.toml`, `CredentialStore` | `client.showErrorDetails = "none"`. A store failure during sign-in or registration shows a short message, never the store's error |
| Inert text | `citewatch.demo.markup` | Quotes, URLs, publisher names and card text are put on one line with markdown syntax written as character references, so a cited page cannot add images or links to the page |

Passkeys use discoverable credentials with user verification required. The store keeps the credential id, public key, signature counter and the date the passkey was added. It keeps no name, e-mail or IP address.

### Why a components-v2 element for WebAuthn

Streamlit has no WebAuthn support, so the page uses a small inline component built with `st.components.v2.component`. It needs no build step. A v2 component runs in the app's own document, not in an iframe. That means `navigator.credentials` sees the app's real origin, and no iframe permission policy can block it: v1 component iframes allow `publickey-credentials-get` but not `publickey-credentials-create`. py_webauthn generates the options and verifies every response on the server. The browser is never trusted with the result.

## Deploy to Streamlit Community Cloud

1. **Create the KV.** Make a free Redis database at [Upstash](https://upstash.com) (pick a region near the app's host, in the US). From its **REST API** section, copy the `UPSTASH_REDIS_REST_URL` (`https://...upstash.io`) and the `UPSTASH_REDIS_REST_TOKEN`. Use the read-write token, not the read-only one.
2. **Make the registration code hash.** Pick a code of 12 to 32 digits that only you know. Run this in a checkout:

   ```
   uv run python -m citewatch.demo.make_code_hash
   ```

   The command asks for the code twice and does not show what you type. It prints the two `CITEWATCH_DEMO_CODE_*` lines. Keep the code somewhere safe; the hash cannot be reversed.
3. **Create the app.** At [share.streamlit.io](https://share.streamlit.io), choose **Create app** and fill in:
   - repository `biplob819/ai-visibility`, branch `main`, main file path `demo/app.py`
   - **Advanced settings** → Python 3.12
   - **App URL**: a custom subdomain, for example `citewatch` (this gives `https://citewatch.streamlit.app`)

   Streamlit installs `demo/requirements.txt`.
4. **Paste the secrets.** In **Advanced settings → Secrets** (later under **Settings → Secrets**):

   ```toml
   # the owner's provider keys (optional: without them, live mode runs on visitors' own keys only)
   ANTHROPIC_API_KEY = "..."
   OPENAI_API_KEY = "..."
   # passkey registration code (from step 2)
   CITEWATCH_DEMO_CODE_HASH = "pbkdf2_sha256$600000$..."
   CITEWATCH_DEMO_CODE_SALT = "..."
   # WebAuthn relying party: the app's exact host name and origin (from step 3)
   CITEWATCH_DEMO_RP_ID = "citewatch.streamlit.app"
   CITEWATCH_DEMO_ORIGIN = "https://citewatch.streamlit.app"
   # the hosted KV (from step 1)
   CITEWATCH_DEMO_KV_URL = "https://....upstash.io"
   CITEWATCH_DEMO_KV_TOKEN = "..."
   ```

   The RP ID must be the app's host name with no scheme, port or path. The origin is `https://` plus that host. If you change the subdomain later, change both values. Passkeys registered under the old name will stop working.
5. **Check it.**
   - Lookup works with no secrets set.
   - In **Live question**, enter the code, create a passkey, then sign out and sign back in with it.
   - Ask one question on the owner's keys. The budget line should drop by about $0.08, and Upstash should show a `citewatch:demo:spend:<date>` key.
   - **Manage app → Logs** should show only four-field lines like `{"at": ..., "cost_usd": ..., "latency_ms": ..., "mode": "live-owner-keys"}`.
   - Ask one question on your own keys. The owner's budget line should not change.

| Secret | Required | What it is |
| --- | --- | --- |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | no | The owner's provider keys. Requests on them count toward the $3 daily cap |
| `CITEWATCH_DEMO_CODE_HASH`, `CITEWATCH_DEMO_CODE_SALT` | yes | The registration code's salted hash (from `make_code_hash`) |
| `CITEWATCH_DEMO_RP_ID`, `CITEWATCH_DEMO_ORIGIN` | yes | The WebAuthn relying party ID (host name) and the origin |
| `CITEWATCH_DEMO_KV_URL`, `CITEWATCH_DEMO_KV_TOKEN` | yes | The Upstash REST endpoint and token: spend and rate-limit counters and registered passkeys |

Live mode stays off until every required secret is set. Lookup mode always works. No secret is ever shown on the page or written to the log.

To rotate the code, run `make_code_hash` again and replace the two lines. Existing passkeys keep working. A hash made before the 12-digit and 600,000-round floors no longer passes; make a new one. To remove every passkey, delete the `citewatch:demo:passkeys` hash in Upstash.

**If registration is locked out** ("Too many registration attempts"), for example because someone has been guessing, it unlocks by itself once a whole clock hour passes with no attempts. To unlock it now, open the Upstash **Data Browser** and delete the keys matching `citewatch:demo:regcode:all:*` (the global counters, one per hour: `citewatch:demo:regcode:all:<hour>`, where `<hour>` is the Unix time divided by 3600). Per-session counters are `citewatch:demo:regcode:s:*`; a fresh browser session starts with its own, so they rarely need deleting. If the lockout keeps coming back, someone is still guessing: rotate the code.

## Run locally

```
uv sync --all-extras
uv run streamlit run demo/app.py
```

Lookup mode needs nothing else. To try live mode locally, put these in `.streamlit/secrets.toml` (git-ignored). Use the SQLite file instead of the KV, and `localhost` as the relying party; browsers allow passkeys on `http://localhost`:

```toml
CITEWATCH_DEMO_CODE_HASH = "..."
CITEWATCH_DEMO_CODE_SALT = "..."
CITEWATCH_DEMO_RP_ID = "localhost"
CITEWATCH_DEMO_ORIGIN = "http://localhost:8501"
CITEWATCH_DEMO_LOCAL_STORE = ".demo-state/demo.sqlite"
```

Do not use the SQLite store on a hosted app: Community Cloud wipes its disk on every restart, which would reset the daily counter and forget every passkey.
