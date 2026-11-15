# A2.1 acceptance criteria

**CIT-01** The Claude extractor returns every `web_search_result_location` citation with `cited_text` as `quoted_span` and its text block as `answer_span`, and every consulted `web_search_result` with `page_age` verbatim, on the recorded fixtures.
**CIT-02** The OpenAI extractor returns every `url_citation` with an answer span taken from the indices (the claim the marker follows), consulted sources from `web_search_call` sources and opened pages, and an answer text without citation markers.
**CIT-03** Citations come only from API citation fields: links typed in the answer text, and URLs only in consulted sources, are never extracted as citations.
**CIT-04** `canonical_url` lower-cases scheme and host, drops fragment, user info and default port, strips `utm_*` and known click IDs, keeps other parameters, and is idempotent (property test); `url_raw` keeps the API's spelling.
**CIT-05** `publisher_of` follows D-4 with fixtures for `www.nhs.uk`, an NHS trust, `www.gov.uk`, `bbc.co.uk`, a `.ac.uk` university and a plain `.com`, and is stable (property test).
**CIT-06** Each answer's unique URL set is derivable from `citations.jsonl` while the raw citation count is kept; `citewatch extract` rebuilds identical files from the store with no keys.
