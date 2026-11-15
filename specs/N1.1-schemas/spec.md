# N1.1 — Schemas and config

**Wave 1. Depends on:** W0.1. **Unblocks:** N1.2, N1.3, N1.4 and, through them, everything else.

## Goal
Every record the study writes or reads has one typed, frozen, validated definition (Tech Spec §4), so the runners, extractor, fetcher, metrics and demo cannot disagree about a field, and every file can be checked by a contract test.

## Outputs (`src/citewatch/schemas/`)
- `_base.py`: `Model` base (frozen, `extra="forbid"`, `allow_inf_nan=False`); tuples for sequences; `FrozenDict` for mappings; `SCHEMA_VERSION = "1.0"`.
- `study.py`: `Intent`, `ModelId`, `StudyQuestion`, `AnswerRecord`, `Citation`, `ConsultedSource` (SCH-01).
- `pages.py`: `DateCandidate`, `PageMeta` with the outcome enum (SCH-02).
- `summary.py`: `Interval` and the summary rows (`ShareRow`, `ConcentrationRow`, `FreshnessRow`, `StaleRow`, `OverlapRow`, `StabilityRow`, `AccuracyRow`, `SupportRow`), `StudySummary` (SCH-03).
- `cards.py`: `DomainCard`, `SupportVerdict`, `HandDateLabel` (SCH-04).
- `config.py`: `StudyConfig` and `load_study_config(path)` with errors naming the file and field; `study.yaml` at the repo root with the §7.1 values (SCH-05).
- `tests/fixtures/v1/`: one JSON fixture per top-level schema; round-trip contract tests checked against an independent list of the Tech Spec §4 schema names (EvalKit L-10).

## Rules
- Consistency is validated, not hoped for: `word_count` matches `answer_text`; `over_length` equals `word_count > word_limit` is enforced where the limit is known (in the stage, not the schema); a `refusal` or `error` answer has no citations in the citation table (checked in A2.1); `Interval.lo ≤ point ≤ hi`, `0 ≤ k ≤ n`; `PageMeta.effective_date` must equal one of its chosen dates and `effective_source` must name that date's source; a rejected `DateCandidate` is never a chosen date; `date_modified < date_published` is invalid.
- Timestamps are timezone-aware UTC; dates are `datetime.date`.
- `Citation.url` must already be canonical: lower-case scheme and host, no fragment (the full canonicaliser lands in A2.1; the schema checks the invariants it can).
- `StudyConfig.max_searches` 1–5, `word_limit` > 0, `stale_days` > 0, `user_location.country == "GB"`, `user_agent` must contain a contact (URL or address) once set; `effort` one of low, medium, high.
- `ModelId` is exactly `claude-sonnet-5-5` or `gpt-6.1-sol` (D-8).

## Out of scope
Parsing provider responses (N1.2, A2.1), the canonicaliser (A2.1), metric computation (M3.1).
