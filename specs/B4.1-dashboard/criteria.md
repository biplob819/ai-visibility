# B4.1 acceptance criteria

**DSH-01** A static, self-contained HTML page (no external requests): share, freshness lag, overlap by intent; a count beside every percentage; intervals drawn and printed.
**DSH-02** Page one carries the scope statement (sourcing, not medical accuracy; 100 questions is directional), coverage, error rates and the support and date check results, each labelled with how it was made.
**DSH-03** Deployed to Cloudflare Pages; the URL serves the same bytes as `results/site/index.html`.
**DSH-04** Every `StudySummary` field has a rendered section (a test walks the schema); every number shown traces to `summary.json`; identity is never carried by colour alone; renders in light and dark.
