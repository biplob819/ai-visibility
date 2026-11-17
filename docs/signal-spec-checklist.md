# Signal spec checklist (B4.3, SIG-01)

The data-product checklist from the PRD's success metrics ("names buyer, unit of value, delivery and pricing logic on one page"), each item mapped to where `docs/signal-spec.pdf` meets it. Rebuild with `uv run python scripts/build_signal_spec.py`.

| Item | Where it is met | Section heading in the PDF |
|---|---|---|
| Buyer named | Publishers, AI labs, agencies and researchers, each with the question they pay to answer | BUYERS |
| Unit of value | One tracked question set × one model × one run, delivered with intervals | PRICING LOGIC |
| Delivery | Scheduled re-runs with a run manifest; JSON results and cards; dashboard; domain lookup; threshold checks | DELIVERY |
| Pricing logic | Cost scales with questions × models × runs; four tiers set by panel size, cadence and raw-record access; no price points | PRICING LOGIC |
| Fields | Share, cited instead, freshness, readability, support, improvement codes (from `PageMeta`, the cards and the measured gaps) | FIELDS |
| Evidence | Four findings and the two checks, each a `summary.json` value with its count and 95% interval | What the first study found |
| Limits | Directional scope; dates only from what pages state; sourcing, not medical accuracy | LIMITS |
