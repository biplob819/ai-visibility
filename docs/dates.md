# How dates are resolved, and their limits

citewatch never guesses a date. For each cited page it collects every candidate date it can
find, rejects implausible ones (keeping them in `page_meta.jsonl` with the rule that rejected
them), and picks one **effective date**: the reviewed date if there is one, else the modified
date, else the published date.

## Where candidates come from

1. **schema.org** JSON-LD: `dateModified`, `datePublished`, `lastReviewed`.
2. **Microdata and RDFa**: the same properties.
3. **Meta tags**: `article:modified_time`, `article:published_time`, `og:updated_time`, Dublin Core.
4. **Visible text**: "Page last reviewed", "Last updated", "Updated on", read day-first.
5. **Sitemaps** listed in robots.txt: the page's `lastmod`.
6. **The search tool's page age** (Claude's search results), converted from "N days ago".
7. **HTTP `Last-Modified`**.

## Rules

- Dates before 1995, or more than a day after the fetch, are rejected.
- An HTTP header or CMS stamp within a day of the fetch is rejected unless another source agrees
  within 7 days (it is usually the server's clock, not an edit).
- A modified date earlier than the published date is rejected.
- Ambiguous numeric dates (05/10/2024), two-digit years and dates missing a day are dropped.
- Precedence for modified and published dates: schema.org, microdata, meta tags, visible text,
  sitemap, page age, HTTP header. Visible text wins for the reviewed date.

## Limits

- Pages that robots.txt disallows, that refuse automated readers, that fail to load or are not
  HTML (PDFs) can only be dated from the search tool's page age, or not at all. They are
  counted with the reason, never guessed.
- Dates readers never see (sitemaps, headers, page age) are often wrong: in the flagship study's
  held-out check, visible-text dates were within 7 days on 12 of 12 judgeable pages, sitemap and
  header dates on 0 of 5 (small samples; see the dashboard's date check).
- The flagship study's date check was agent-checked and owner-approved, on 55 pages the parser
  was never tuned on; 27 dated pages could be judged.
