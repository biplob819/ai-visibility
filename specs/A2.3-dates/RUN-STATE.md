# A2.3 run state

**Now:** built and converged; verifier pass 1; DAT-04 labels await the owner.

## History
- 2026-11-16 — spec and criteria written; started after A2.2 green. extruct for JSON-LD, microdata and RDFa; python-dateutil for day-first text.
- 2026-11-16 — built `src/citewatch/dates/` and wired it into `citewatch fetch` (candidates stored through `analyse`, sitemaps from robots.txt, `page_meta.jsonl`). Built the DAT-04 set with `scripts/build_date_fixtures.py`: 24 UK health URLs fetched politely with the flagship user agent (audit OK); NICE, NHS inform and Mayo Clinic disallow citewatch, Mind answered 403, patient.info 404; 21 trimmed snapshots kept. The real pages found three resolver errors before any label: extruct drops JSON-LD without `@context` (WHO), control characters break strict JSON, and NHS "Media last reviewed" lines were read as page review dates (D-44). A fourth showed in the drafted evidence: timestamps were shifted to UTC before taking the date (fixed: the page's own time zone). Labels drafted from the snapshots, status `draft`; the owner confirms or corrects them on https://claude.ai/artifact/7EYYRK8LLBiwXHVgdjD7YR.

## Known limits
