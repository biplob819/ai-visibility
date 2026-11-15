# A2.2 — Polite fetcher

**Wave 2. Depends on:** N1.3. **Unblocks:** A2.3 (dates read the bodies this node holds in memory), M3.2 (support-sample text), A2.4.

## Goal
Every cited page is requested the way a careful person would: only pages a model actually cited, only where robots.txt allows our user agent, never faster than one request a second per host, never again after a refusal, and every request written down so gate 8 can prove it afterwards (Tech Spec §7.2, NFR1, B3, B8). Bodies never reach disk except the support sample's main text (NFR6).

## Outputs (`src/citewatch/fetch/`)
- `robots.py`: `RobotsCache` per origin (scheme, host, port), fetched once per study run through the polite client and parsed with `protego` (RFC 9309 longest match, D-10). 2xx parses; 404, 410 and other 4xx allow everything; 401 and 403 disallow everything (stricter than RFC 9309, on purpose); 5xx, a timeout or a transport error disallow everything. Matching uses the product token `citewatch` (FET-01).
- `rate.py`: `HostLimiter`: one grant per host per interval (1 s in production, plus a small margin so wall-clock `at` gaps stay at or above 1.0 s), shared by page, robots, redirect-hop and sitemap requests; at most 8 requests in flight at once (FET-02).
- `client.py`: `PoliteClient(user_agent, log, robots, limiter, transport=None)`. `get(url, kind)` follows at most 5 redirects by hand, checking robots and the limiter on every hop (a hop to a new host checks that host's robots); a disallowed hop is logged as `robots_disallowed` and stops. 10 s timeout. At most 2 retries on a transport error, 5xx or 429 (a `Retry-After` up to 60 s is honoured; longer gives up); none after 401, 403, 451 or a robots refusal. The user agent is the study's, constant for the run (FET-03, FET-04).
- Page memory: before any request the client consults a per-page history seeded from every earlier fetch log of the study, using the same page identity as the gate-8 audit; it never makes a fourth request for a page, never requests a page again after a block, and reuses a result already fetched in this run (FET-04, FET-05).
- `pages.py`: `fetch_pages(urls, ..., analyse=None, keep_text=frozenset())`: fetches each canonical URL once across runs (the raw-store `fetch` stage keyed on the URL alone), `text/html` only, bodies read in a stream and cut at 5 MB (`too_large`), outcomes `ok`, `robots_disallowed`, `blocked` (401, 403, 451), `gated` (a password field or `isAccessibleForFree: false` on a 200), `not_html`, `fetch_error`. The store gets url, final URL, status, selected headers, robots decision, outcome, hops and `analyse(page)`'s fields, never the body. The body stays in memory for `analyse` (dates, A2.3) and is dropped; for URLs in `keep_text` the main text (scripts, styles and tags removed) is written to the body cache (`$CITEWATCH_BODY_CACHE` or `~/.cache/citewatch/bodies/`) (FET-05, FET-06, FET-07).
- `log.py`: `FetchLog(path)` appends one locked JSON line per request or robots refusal with the §7.2 fields (`at` is the request's start time, UTC); `citewatch fetch` writes `<study>/data/fetch_log.jsonl`, which gate 8 audits with `scripts/fetch_audit.py` (FET-08).
- CLI: `citewatch fetch [--dry-run]` reads the canonical URLs from `<study>/data/citations.jsonl` (written by `extract`, A2.1), skips URLs already fetched, and prints hosts, URL counts and the minimum wall clock at 1 req/s with 8 hosts in flight; `--dry-run` needs no keys and makes no request. Date resolution joins in A2.3.

## Rules
- Consulted-only URLs are never fetched; the input is canonical citation URLs only.
- A page whose host's robots.txt returned 401, 403 or 5xx is logged `robots_disallowed` without a request.
- No cookies are kept, no login is attempted, no paywall is bypassed (B8).
- Every line of every fetch log written by the tests passes `scripts/fetch_audit.py`.

## Out of scope
Date candidates and resolution (A2.3), sitemaps' content (A2.3 uses `PoliteClient.get(kind="sitemap")`), the support sample draw (M3.2), JavaScript rendering (never).
