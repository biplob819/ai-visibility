# A2.3 — Date resolver

**Wave 2. Depends on:** A2.2. **Unblocks:** A2.4 (smoke run), M3.1 (freshness metrics), M3.3 (hand date check).

## Goal
Every cited page gets every date it states, each with its source and the rule that rejected it if one did, and one chosen date per kind by a fixed precedence, so freshness findings rest on auditable dates rather than build stamps or fetch times (Tech Spec §6.2, §7.3, D-5, D-6, C3, E4).

## Outputs (`src/citewatch/dates/`)
- `candidates.py`: the seven sources of §7.3 as `DateCandidate`s: JSON-LD (extruct, walking `@graph` and nested objects: `dateModified`, `datePublished`, `lastReviewed`), microdata and RDFa (schema.org properties), meta tags (`article:modified_time`, `article:published_time`, `og:updated_time`, `DC.date.modified`, `DC.date.issued`, `last-modified`), visible text ("Page last reviewed", "Next review due", "Last updated", "Updated on", "Published", day-first UK), sitemap `lastmod` for the exact canonical URL, Claude `page_age` (relative "198 days ago" converted with the answer's `answered_at`, D-35, or an absolute date), HTTP `Last-Modified` (DAT-01). `review_due` is captured from the NHS pattern (DAT-06).
- `rules.py`: plausibility rules, each rejection named: `out_of_range` (before 1995-01-01 or more than a day after `fetched_at`), `dynamic_header` (Last-Modified within 24 h of `fetched_at`), `cms_stamp` (schema or meta modified within 24 h of `fetched_at` with no other source within 7 days of it), `modified_before_published` (DAT-02).
- `resolve.py`: precedence per kind (reviewed: visible text > schema.org > microdata; modified and published: schema.org > microdata > meta > visible text > sitemap > page_age > HTTP header); within one source the latest modified, the earliest published; every candidate kept; a valid `PageMeta` with chosen values, sources and the effective date (reviewed, else modified, else published) (DAT-03).
- `sitemaps.py`: sitemaps only from robots.txt `Sitemap:` lines (kept in the robots store), fetched through the polite client, streamed and capped at 10 MB (gzip counted decoded), XML parsed without entity expansion, at most one level of sitemap index; only `lastmod` for the URLs the study needs is kept, cached per host in the store (DAT-05).
- The fetch stage stores each page's candidates through `analyse` (A2.2); `citewatch fetch` then reads sitemaps and writes `data/page_meta.jsonl` from the store, `consulted.jsonl` page ages and `answers.jsonl` times.
- DAT-04: a 20-page test set of real UK health pages, trimmed to their date-bearing parts and stored as fixtures, with owner-confirmed labels; the resolver must match them. Tuning set only (D-6): the held-out hand check is M3.3.

## Rules
- Nothing is invented: a page with no usable date has none.
- A blocked or gated page can still get a date from `page_age` (no fetch needed).
- Sitemaps follow every fetch rule of A2.2 (robots, rate, budget, log, audit).

## Out of scope
Freshness metrics (M3.1), the held-out hand check (M3.3), JavaScript-rendered dates (never).
