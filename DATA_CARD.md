# Data card: UK health and fitness study

What this study collects, what it discards, and how it treats the sites it reads. Written in the present tense only for what the code already does; anything later nodes will add is marked as planned.

## What is collected

- **Answers.** For each of 100 frozen questions (`studies/uk-health/questions.jsonl`), Claude and GPT are asked with web search on, from a London (GB) location, with a 150-word instruction. The raw API responses are stored verbatim and gzipped under `data/raw/ask/`, with the request, timing, usage and cost. Each paid call writes one line to `data/spend-ledger.jsonl` the moment it returns.
- **Citations and consulted sources.** Only the APIs' own citation fields count as citations (Claude `web_search_result_location`, OpenAI `url_citation`); a link typed in the answer text never does. URLs are canonicalised (tracking parameters removed; the API's spelling kept as `url_raw`) and mapped to a publisher by the public suffix rule of D-4. Written to `data/answers.jsonl`, `data/citations.jsonl` and `data/consulted.jsonl`.
- **Page metadata.** Each cited page is fetched once for the whole study. The store keeps its status, final URL, a few response headers, the robots decision and every date the page states (structured data, meta tags, visible "reviewed" or "updated" lines, sitemap `lastmod`, Claude's page age, Last-Modified), each with its source and any rule that rejected it. Written to `data/page_meta.jsonl`.

## What is discarded

- **Page bodies.** A fetched page is held in memory only while its dates are read, then dropped. No page body or markup is stored; a storage audit (gate 9) fails the build if any is.
- **Support sample (M3.2):** for the 49-citation support sample only, the page's main text was kept in a local cache outside the repository for the support check, and deleted when scoring was finalised (`citewatch score --finalise`, 17 November 2026). Only verdicts and one-sentence quotes remain.

## Politeness

- Only pages a model actually cited are fetched; pages a search only returned are never fetched. For each cited site, citewatch also reads robots.txt and the sitemaps robots.txt lists (for `lastmod` dates), once per site for the whole study.
- robots.txt is read once per site for the whole study and obeyed for the `citewatch` user agent with RFC 9309 longest-match rules (protego); a robots.txt answering 401, 403, 5xx or not at all disallows the whole site. Every redirect hop, on any host, is checked again.
- At most one request per second per site, spaced from the moment each request is actually sent, and at most eight requests in flight. At most three requests per page across the whole study, and none after a 401, 403, 451 or a robots refusal.
- Every request carries `citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)` and no cookies or credentials. Login walls and paywalls are recorded as `gated`; nothing is worked around.
- Every request is logged in `data/fetch_log.jsonl`; gate 8 replays the log and fails the build on any breach.

## Quoted spans

Claude's `cited_text` (the passage the API returns as supporting a citation, usually a sentence or a short span) is stored as the citation's quoted span. Answers are the models' own text. The raw store also keeps the APIs' search results as returned, including Claude's `encrypted_content`, which is not readable page text. Nothing else from a page is stored.

## Limits

- Two models, one location (London), one instruction and 100 questions: findings describe this setup, not AI search in general.
- Dates come only from what pages state; a page with no usable date is reported as undated, never guessed. Ambiguous numeric dates (05/10/2024) are dropped.
- Sites that disallow citewatch (seen so far: NICE, NHS inform, Mayo Clinic) or block it can be dated only from Claude's page age.
- **Support check (M3.2):** 49 sampled citations, judged by two AI judges from different families (claude-opus-5-5, gpt-6.1-sol, via EvalKit) and labelled by the owner (OWNER D-62). The owner labelled all 49 supported; the judges called 38–45% of them unsupported, so judge–owner kappa is not informative. One citation is unjudged after a failed refetch (D-67) and one after EvalKit could not judge it.
- **Date check (M3.3):** 55 held-out pages, agent-checked, owner-approved, not hand-checked (OWNER D-63, D-64). The parser's date was within 7 days on 18 of 27 judgeable dated pages (67%, Wilson 48–81%); 23 dated pages show a reader no date and are counted, not scored. Every judged date was either exact or more than 7 days off.
