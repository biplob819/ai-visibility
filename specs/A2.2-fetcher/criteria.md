# A2.2 acceptance criteria

**FET-01** robots.txt is parsed with `protego` per §7.2: the longest-match case (`Allow: /` before `Disallow: /private`) disallows `/private`; 404/410 allow; 401/403/5xx/timeout disallow every page on that host without a request; robots is fetched once per origin; every redirect hop to a new host is checked against that host's robots.
**FET-02** Requests to one host, including robots, redirect hops and sitemap requests, start at least 1.0 s apart in the fetch log even under concurrency; no more than 8 requests are in flight at once.
**FET-03** Every request carries the study's user agent (`citewatch/<version> (+<project URL>; <contact>)`), unchanged across the run, and robots rules are matched for the `citewatch` token.
**FET-04** 10 s timeout; at most 2 retries on transport errors, 5xx and 429 (Retry-After honoured up to 60 s); no retry after 401, 403, 451 or a robots refusal; never a fourth request for a page and never a request after a block, across runs.
**FET-05** Only canonical URLs from `citations.jsonl` are fetched, each once across runs; `fetch --dry-run` lists hosts, URL counts and the minimum wall clock with no keys and no requests.
**FET-06** Only `text/html` bodies are read, cut at 5 MB (`too_large`); bodies stay in memory for `analyse` and are dropped; only `keep_text` URLs write main text to the body cache; the store holds no body.
**FET-07** A 200 page with a password field or `isAccessibleForFree: false` is recorded `gated` with no further request.
**FET-08** `fetch_log.jsonl` holds one line per request or robots refusal with url, host, at (request start, UTC), attempt, status, bytes, robots, outcome and user agent; every log the tests produce passes `scripts/fetch_audit.py`, and the fetcher's page identity matches the audit's.
