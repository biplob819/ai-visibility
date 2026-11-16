# Data card: UK health and fitness study

What this study collects, what it discards, and how it treats the sites it reads. Written in the present tense only for what the code already does; anything later nodes will add is marked as planned.

## What is collected

- **Answers.** For each of 100 frozen questions (`studies/uk-health/questions.jsonl`), Claude and GPT are asked with web search on, from a London (GB) location, with a 150-word instruction. The raw API responses are stored verbatim and gzipped under `data/raw/ask/`, with the request, timing, usage and cost. Each paid call writes one line to `data/spend-ledger.jsonl` the moment it returns.
- **Citations and consulted sources.** Only the APIs' own citation fields count as citations (Claude `web_search_result_location`, OpenAI `url_citation`); a link typed in the answer text never does. URLs are canonicalised (tracking parameters removed; the API's spelling kept as `url_raw`) and mapped to a publisher by the public suffix rule of D-4. Written to `data/answers.jsonl`, `data/citations.jsonl` and `data/consulted.jsonl`.
- **Page metadata.** Each cited page is fetched once for the whole study. The store keeps its status, final URL, a few response headers, the robots decision and every date the page states (structured data, meta tags, visible "reviewed" or "updated" lines, sitemap `lastmod`, Claude's page age, Last-Modified), each with its source and any rule that rejected it. Written to `data/page_meta.jsonl`.

## What is discarded

- **Page bodies.** A fetched page is held in memory only while its dates are read, then dropped. No page body or markup is stored; a storage audit (gate 9) fails the build if any is.
- **Planned (M3.2):** for the 50-citation support sample only, the page's main text will be kept in a local cache outside the repository for the support check and hand labelling, and deleted when scoring is finalised.

## Politeness

- Only pages a model actually cited are fetched; pages a search only returned are never fetched.
- robots.txt is read once per site for the whole study and obeyed for the `citewatch` user agent with RFC 9309 longest-match rules (protego); a robots.txt answering 401, 403, 5xx or not at all disallows the whole site. Every redirect hop, on any host, is checked again.
- At most one request per second per site, spaced from the moment each request is actually sent, and at most eight requests in flight. At most three requests per page across the whole study, and none after a 401, 403, 451 or a robots refusal.
- Every request carries `citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)` and no cookies or credentials. Login walls and paywalls are recorded as `gated`; nothing is worked around.
- Every request is logged in `data/fetch_log.jsonl`; gate 8 replays the log and fails the build on any breach.

## Quoted spans

Claude's `cited_text` (the sentence a citation supports) is stored as the citation's quoted span. Answers are the models' own text. Neither reproduces a page beyond the single sentence the API itself returns.

## Limits

- Two models, one location (London), one instruction and 100 questions: findings describe this setup, not AI search in general.
- Dates come only from what pages state; a page with no usable date is reported as undated, never guessed. Ambiguous numeric dates (05/10/2024) are dropped.
- Sites that disallow citewatch (seen so far: NICE, NHS inform, Mayo Clinic) or block it can be dated only from Claude's page age.
- **Planned:** the support check (M3.2) and the 50-date hand check (M3.3) will measure how often a cited page supports its claim and how accurate the dates are; until then neither rate is known.
