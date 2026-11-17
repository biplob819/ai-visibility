# D5.1 acceptance criteria

**CRD-01** `results/domain_cards.json` built by `citewatch score` from `summary.json` and the frozen study data; every cited publisher has one valid `DomainCard`; every share on a card equals the matching `summary.json` row; byte-identical on a rerun.
**CRD-02** `lookup()` normalises input (scheme, `www.`, path, port, case) through the extractor's `publisher_of` (contract test that they are one function); returns the card, or a not-cited result naming N answers and the top publishers for the intent; under 1 second on the flagship cards.
**CRD-03** `cited_instead` per §9, ranked by count with name tie-breaks, never the publisher itself.
**IMP-01** Each card carries improvement rows for the codes in the spec whose count is above zero; counts reproduce from `summary.json`, `page_meta.jsonl`, `fetch_log.jsonl` and `support_verdicts.jsonl`.
**IMP-02** Every row has a fix and the evidence count with its denominator and source file; no wording claims or denies medical accuracy (a test scans every finding and fix).
