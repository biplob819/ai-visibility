# A2.1 — Citation extraction and publisher mapping

**Wave 2. Depends on:** N1.2. **Unblocks:** A2.4 (smoke run), M3.1 (metrics), M3.2 (support check), D5.1 (domain cards).

## Goal
Turn every stored answer envelope into an answer record, its citations and the sources it consulted, using only the APIs' own citation fields (B2), with one canonical URL and one publisher per page so shares count publishers, not tracking variants or hostnames (Tech Spec §3, §5, D-4, H5, H6, C1, C2).

## Outputs (`src/citewatch/extract/`)
- `urls.py`: `canonical_url(url)`: lower-case scheme and host (IDN as punycode), no fragment, user info or default port, `utm_*` and known click IDs removed, other query parameters kept in order, percent-encoding normalised; idempotent (CIT-04). `publisher_of(url_or_domain) -> (publisher, group)` per D-4 on the bundled Public Suffix List snapshot (no network): `www.nhs.uk` → `nhs.uk`; `guysandstthomas.nhs.uk` → itself, group `nhs.uk`; the same for `gov.uk`, `police.uk`, `ac.uk`, `sch.uk`; otherwise the registrable domain (CIT-05).
- `extractors.py`: Claude: `web_search_result_location` citations on text blocks with `cited_text` and the text block as the answer span; consulted sources from `web_search_tool_result` with `page_age` verbatim (CIT-01). OpenAI: `url_citation` annotations; the answer span is the text the marker follows, back to the previous marker or the paragraph start; consulted sources from every `web_search_call` action's sources and opened pages (CIT-02). Links typed in the answer text are never citations (CIT-03). OpenAI's inline citation markers are removed from the counted answer text (D-43).
- `stage.py`: `run_extract(study_dir, cfg)` rebuilds `data/answers.jsonl` (`AnswerRecord`), `data/citations.jsonl` (every citation occurrence with its ordinal) and `data/consulted.jsonl` (unique per answer, `cited` set) from the raw store only; `unique_cited_urls` gives each answer's unique URL set while the raw count stays in the rows (CIT-06). One odd envelope is reported, never stops the stage.
- CLI: `citewatch extract [--json]`, no keys, no network.

## Rules
- Pure: the same store gives byte-identical files.
- A citation URL that cannot be a web page (not http(s), no host) is skipped and counted, never invented or repaired.
- Partial answers (`ask_partial`) are not extracted; they are asked again.

## Out of scope
Transport-error counts per model (from `run.log`, M3.1), dates (A2.3), metrics (M3.1).
