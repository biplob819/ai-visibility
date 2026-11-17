# Responsible use

citewatch measures **sourcing**: which web pages AI answers with web search cite, who
publishes them, and how fresh those pages are. It is a measurement and research tool.

## What it is not for

citewatch is **not** a tool for gaming AI answers. It gives no advice on how to make a model
cite a page, and its reports never will (boundary B9). The improvement notes in the domain
cards say what citewatch could not read on a cited page (a hidden date, a robots.txt that did
not answer); they are about making a page's facts readable, not about steering a model.

Please do not use citewatch to:

- scrape sites: it fetches only URLs that an AI answer in your study cited, once each;
- work around a block, a login or a paywall: it never does, and records the page as
  `blocked` or `gated` instead (B8);
- present results as more certain than they are: every share and rate carries its interval
  and its count, so report them together.

## The politeness floor cannot be lowered

Every study, ours or yours, fetches under the same floor (D-25):

| Rule | Value |
|---|---|
| robots.txt | always obeyed, per origin, with RFC 9309 longest-match rules; an unreadable robots.txt (5xx, no answer) disallows the host |
| Rate | at most 1 request per second per host |
| Concurrency | at most 8 requests in flight across all hosts |
| Retries | at most 2 (3 requests per page), only for timeouts, 5xx and 429; never after 401, 403 or 451 |
| What is fetched | only the canonical URLs your study's answers cited, plus robots.txt and the sitemaps it lists |
| User agent | must start with `citewatch/<version>` and name a real project page or address |

There is no setting to loosen any of this: `study.yaml` refuses unknown keys, `citewatch
fetch` has no rate, robots, retry or concurrency flag, and no environment variable is read
for any of them. Proxy variables are ignored too, so every request goes through the logged
client. Tests try each route (`tests/fetch/test_politeness_floor.py`). Every request is
written to `data/fetch_log.jsonl`, and `scripts/fetch_audit.py` checks a log against these
rules. You may always be stricter, for example by running fewer questions.

## No telemetry

citewatch sends nothing about you or your study to its authors or to any third party. It
has no analytics, no update check and no crash reporting. The dashboard it builds is a
single self-contained HTML file that loads nothing from the network.

## Privacy: what is stored, and what is sent where

**Sent over the network, and only to these:**

- **The AI providers you configure** (Anthropic, OpenAI), with your own API keys: each
  question, your study's location settings and instruction, and, for the optional support
  check, the cited passage and page text being judged.
- **The sites your answers cited**: one request per cited page, plus robots.txt and listed
  sitemaps on those hosts, with your study's user agent.

**Stored on your machine, in the study folder:**

- `data/raw/`: the providers' responses, verbatim (answer text, citations, search metadata).
- `data/*.jsonl`: answers, citations, consulted sources, page dates (`page_meta`), the fetch
  log, the spend ledger, and any labels you import.
- `results/`: `summary.json`, domain cards and the dashboard.

**Not stored:** page HTML and page text. Bodies are read in memory to find dates and are
dropped. The one exception is the support check's sample, whose extracted text is cached
outside the repository (`~/.cache/citewatch/bodies`, or `CITEWATCH_BODY_CACHE`) until
`citewatch score --finalise` deletes it.

**Keys:** read from the environment or a `.env` file you create; never printed, logged or
written into any output (`citewatch doctor` reports only whether each key is set).

If you publish a study, publish `results/` and the data files you choose; check that your
questions and labels contain nothing personal first.

## Reporting a problem

Site owners can reach whoever ran a study through the contact in its user agent. If
citewatch itself fetched your site in a way that breaks these rules, please open an issue at
<https://github.com/biplob819/ai-visibility/issues>, or follow [SECURITY.md](../SECURITY.md)
for anything sensitive.
