# D5.1 — Domain cards, lookup and the improvement report

**Wave 5. Depends on:** M3.1, S3.1. **Unblocks:** D5.2.

## Goal
One card per cited publisher in `results/domain_cards.json`, built from `summary.json` and the frozen study data, so the demo can answer "is my site cited, how often, how fresh, and what would help?" without calling a model (Tech Spec §9, US7). Each card carries an improvement report (OWNER D-65): why the publisher is or isn't cited, each reason paired with a concrete fix and the evidence count behind it.

## Pieces
- `citewatch.cards.build_cards(base, cfg, questions, summary)` → `DomainCard`s, every cited publisher in the scored runs, sorted by citations then name.
  - `share_by_model`: presence share per `model/run-N` (from `summary.share`, intent unset).
  - `share_by_intent`: presence share per `intent/model/run-N`.
  - counts: citations, answers citing, questions citing; `median_freshness_lag_days` and `dated_pages` from the publisher's pooled `FreshnessRow`.
  - `cited_instead` (§9): on questions where the publisher was cited by one model or run but not another, the publishers cited in the answers that left it out, ranked by count (ties by name), top 5.
  - `improvement`: `Improvement` rows (code, finding, fix, count, of, source).
- `citewatch.cards.lookup(query, cards, intent=None)`: strips scheme, `www.`, path and port, maps through the extractor's `publisher_of` (one function, contract-tested), returns the card or a `NotCited` result: "not cited in any of the N answers in this study" plus the most-cited publishers for the chosen intent.
- `citewatch score` writes `results/domain_cards.json` after `summary.json`.

## Improvement codes (deterministic; counts over the publisher's cited pages in the scored runs; D-69)
| code | finding | fix | sources |
|---|---|---|---|
| `intent_absent` | cited on ≥5 questions across ≥2 intents but on none of another intent (noted as possibly outside the site's remit) | if the site covers it, answer such questions plainly; who is cited most on those questions | summary.json |
| `undated` | cited pages that loaded but state no date citewatch could read | add a visible "last updated" date and schema.org `dateModified` | page_meta.jsonl |
| `hidden_date` | loaded pages dated only by sitemap, HTTP header or the search tool's page age, which readers never see | show the date on the page | page_meta.jsonl |
| `stale` | loaded pages cited on time-sensitive questions (§6.3), dated more than `stale_days` before the latest such answer | update and re-date if guidance changed; a visible reviewed date if not | page_meta, answers, questions |
| `robots_blocked` | pages the site's own robots.txt (read with HTTP 200) disallows for citewatch's reader | decide whether independent checkers may read them | page_meta, fetch_log |
| `robots_unreadable` | pages on a host whose robots.txt never returned 200 (the fetcher then treats the host as disallowed) | serve robots.txt to well-behaved readers | page_meta, fetch_log |
| `blocked` | pages refused to automated readers or behind a sign-in | let well-behaved readers load public guidance | page_meta.jsonl |
| `not_html` | cited documents (PDFs and the like) with no machine-readable date | publish key guidance as an HTML page with a visible date | page_meta.jsonl |
| `fetch_error` | pages that failed to load (e.g. 404) | fix or redirect the URL | page_meta.jsonl |
| `unsupported` | support-sample citations both AI judges found not stated on the page, which the owner's check did not find supported | state the key fact in the page text | support_verdicts, support_labels |

A code appears only when its count is above zero. Wording never judges medical accuracy (NFR4), and never states more about a site than the data shows.

## Not in scope
The demo page (D5.2); the dashboard (B4.1).
