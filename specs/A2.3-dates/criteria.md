# A2.3 acceptance criteria

**DAT-01** Candidates come from all seven §7.3 sources (JSON-LD including `@graph` and nested objects, microdata, RDFa, the listed meta tags, the visible-text patterns read day-first, sitemap `lastmod` for the exact URL, Claude `page_age` relative or absolute converted with `answered_at`, HTTP `Last-Modified`), each with source and evidence of at most 120 characters.
**DAT-02** The four plausibility rules reject exactly the candidates they should, naming the rule, and a rejected candidate stays in the list.
**DAT-03** Precedence picks the chosen value and source per kind as §7.3 states; the effective date is reviewed, else modified, else published; every candidate is kept; output validates as `PageMeta`.
**DAT-04** The 20-page test set (trimmed snapshots with owner-confirmed labels, stored as fixtures) passes: chosen reviewed, modified and published dates match the labels.
**DAT-05** Sitemaps are read only from robots.txt `Sitemap:` lines, through the polite client (robots, rate, budget, log), streamed with a 10 MB decoded cap, without XML entity expansion, one index level at most, cached per host; only needed URLs' `lastmod` is kept.
**DAT-06** `review_due` is captured from "Next review due" text and kept with the page's dates.
