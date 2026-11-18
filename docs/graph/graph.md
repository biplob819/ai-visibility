# AI Visibility build graph

Source of truth for build-node dependencies. Parsed by `scripts/harness_lib.py`.
A node may start only when every node in its `Depends on` cell is green (all its rows in `catalog.tsv` are green).
Edge rules: no cycles; a node inherits the constraints of what it depends on; `Verified by` must pass before a node flips green.
Generated from AI Visibility Tech Spec §12.2 on 2026-11-15 (B4.5 added by OWNER D-23); edit here from now on and keep the Tech Spec in sync.


## Wave 0 — harness

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **W0.1** | Repo and harness | — | node_converge + verifier | uv project, CI, ported harness scripts with `--self-test`, records seeded, verifier template | — |

## Wave 1 — core

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **N1.1** | Schemas and config | W0.1 | node_converge + verifier | §4 schemas, `study.yaml` loader, results format v1 fixtures | US1–US5 |
| **N1.2** | Answer runners and cost model | N1.1 | node_converge + verifier | Claude and OpenAI runners (§7.1), `prices.yaml`, pre-run estimate, spend ledger, recorded response fixtures | US1 |
| **N1.3** | Store, ledger and CLI skeleton | N1.1 | node_converge + verifier | Raw store, `run.log`, Typer CLI with `--dry-run`, `--max-cost`, `--json`, exit codes, `doctor` | US1 |
| **N1.4** | Questions, pre-registration, data card | N1.1 | node_converge + verifier | Rubric, 100 frozen questions, `preregistration.md`, `DATA_CARD.md` | US1, US3, US5 |

## Wave 2 — collection pipeline

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **A2.1** | Citation extraction and publisher mapping | N1.2 | node_converge + verifier | Both extractors, consulted sources, `canonical_url`, `publisher_of` | US1, US4 |
| **A2.2** | Polite fetcher | N1.3 | node_converge + verifier | §7.2 in full, fetch log | US2 |
| **A2.3** | Date resolver | A2.2 | node_converge + verifier | §7.3 candidates, rules and precedence; 20-page test set passing | US2, US5 |
| **A2.4** | Smoke run | N1.2, N1.3, N1.4, A2.1, A2.3 | node_converge + verifier | 10 questions × 2 models for real; measured cost model; golden fixture; parity report | US1, US5 |

## Wave 3 — measurement

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **M3.1** | Metrics and statistics | A2.1, A2.3 | node_converge + verifier | §6 in DuckDB plus bootstrap, `summary.json` writer | US1–US5 |
| **M3.2** | Support check | A2.1, A2.2 | node_converge + verifier | §8.1 sampling, EvalKit judging, labelling sheet, agreement, clean-up | US5 |
| **M3.3** | Hand date check | A2.3 | node_converge + verifier | §8.2 sampling, sheet, error rates | US5 |

## Wave 3 — study runs

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **S3.1** | Study runs 1 and 2 | A2.4 | node_converge + verifier | Both runs collected, extracted, fetched, audited, reconciled and frozen (§13) | US1–US5 |

## Wave 4 — write-up and release

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **B4.1** | Findings dashboard and deploy | M3.1, M3.2, M3.3, S3.1 | node_converge + verifier | Static dashboard on Cloudflare Pages | US1–US5 |
| **B4.2** | The post and charts | B4.1 | node_converge + verifier | Post with charts generated from `summary.json` | US6 |
| **B4.3** | Signal spec | M3.1, S3.1 | node_converge + verifier | One-page PDF: fields, buyers, delivery, pricing logic | US6 |
| **B4.4** | Public repo | B4.2, B4.3 | node_converge + verifier | README, licence, data card, decisions, history audit, repo public | US5, US6 |
| **B4.5** | Open-source packaging and v0.1.0 | B4.4 | node_converge + verifier | PyPI `citewatch`, `init`, run-your-own-study and responsible-use docs, community files, release workflow, import contract test, tag v0.1.0 | US5, US7 |

## Wave 5 — demo and portfolio

| Node | Title | Depends on | Verified by | Deliverable | Stories |
| --- | --- | --- | --- | --- | --- |
| **D5.1** | Domain cards and lookup | M3.1, S3.1 | node_converge + verifier | `domain_cards.json`, `lookup()` | US7 |
| **D5.2** | Demo page and live mode | D5.1, N1.2 | node_converge + verifier | Streamlit page in `portfolio-demos`, guarded live mode | US7, US8 |
| **D5.3** | Project page, walkthrough GIF, supporting notes | B4.5, D5.2 | node_converge + verifier | Case study page, walkthrough GIF (OWNER D-86), how-I-built-it note, one-page PRD | US6 |
