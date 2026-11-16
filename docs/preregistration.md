# Pre-registration: UK health and fitness study

Frozen on 2026-11-16, before any study run (D-7). Nothing below may change after run 1; a test fails if this file or the question set changes (QST-03).

## The question set

- `studies/uk-health/questions.jsonl`: 100 questions, 20 per intent (symptoms, treatment, nhs_services, fitness, nutrition), 57 time-sensitive, approved by the study owner on 2026-11-16 and re-frozen the same day with the time-sensitive flags aligned to the rubric (OWNER D-51). sha256 `aaa3a348ab5844e2ad1fac47e0b68a4b53fb08e1354a0f303cc3d60186bba071`.
- Written to `studies/uk-health/RUBRIC.md`, committed before any question. sha256 `e96e0741be589782a6c8e3aaf25318d595f54a4cf4f2b4a63f5e3bfaa38e89e9`.

## Settings (from `studies/uk-health/study.yaml`)

```yaml
# The flagship study (Tech Spec §7.1). Copy this folder, or run `citewatch init`, to run your own.
name: uk-health-2026-11
questions_path: questions.jsonl
intents: [symptoms, treatment, nhs_services, fitness, nutrition]
ts_reasons: [services, eligibility, waiting, prices, guidance]   # the rubric's time-sensitive clauses (N1.4 writes RUBRIC.md)
models: [claude-sonnet-5-5, gpt-6.1-sol]
effort: medium            # OWNER D-8: the same effort on both models
user_location:
  type: approximate
  country: GB
  city: London
  region: England
  timezone: Europe/London
max_searches: 3
word_limit: 150
stale_days: 365
seeds:
  order: 20261115
  support_sample: 51
  hand_sample: 52
  bootstrap: 53
max_cost_usd: 25          # per paid command; OWNER D-19 asks before any run above $25
user_agent: "citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)"
```

## Seeds

- `order` 20261115: question order per run.
- `support_sample` 51: the 50-citation support sample (M3.2).
- `hand_sample` 52: the 50-date hand check (M3.3), held out from the date resolver's tuning set (D-6).
- `bootstrap` 53: the single question-cluster resample matrix used by every interval.

## Thresholds

- Model comparisons: two-sided tests at a family-wise alpha of 0.05, Holm-corrected across the top-10 publishers compared (§6.6).
- Intervals are 95% (percentile bootstrap; Wilson for the 50-item hand checks).
- Stale means older than `stale_days` (365) in `study.yaml`; over-length means more than `word_limit` (150) words.

## Exclusions and counts

- Refusals and transport errors are excluded from share denominators and counted per model.
- Zero-citation answers stay in every denominator; their count is reported.
- Over-length answers (more than 150 words) are included; the rate is reported per model.
- Cited pages modified after the answer are excluded from lag and counted as `modified_after_answer`.
- Undated pages are excluded from lag and stale rates and counted, with the fetch outcome as the reason.
- Questions where both models cite nothing are excluded from cross-model overlap and counted.
- Pages robots.txt disallows, blocked (401, 403, 451) or gated are never worked around; they keep only dates that need no fetch (Claude's page age).

## Known limits of the question set

- Recency wording ("current", "latest", "now") appears only in time-sensitive questions, so comparisons of freshness between time-sensitive and other questions mix topic with wording.
- The questions are about UK care, so 13 name the NHS and 10 mention a GP; this is a natural UK slant, not a request for any source, and is reported as a limit.

## Metric definitions (Tech Spec §6, verbatim)

## 6. Metric definitions

Defined here once, copied verbatim into `docs/preregistration.md`, and frozen before run 1 (D-7). Notation: an **answer** is a (run, question, model) record; a **valid answer** has no transport error and no refusal. P(a) is the set of publishers among answer a's unique canonical URLs.

### 6.1 Share (US1, FR7)

- **Presence share (headline).** For publisher p and a slice S of valid answers (model × intent × run): share(p) = |{a ∈ S : p ∈ P(a)}| / |S|. Zero-citation answers stay in the denominator.
- **Weighted share (secondary).** Each valid answer with citations gives weight 1 / |URLs(a)| to each unique URL's publisher; share(p) = Σ weights / |S with citations|. Sums to 1 over publishers.
- **Consulted share.** Presence share computed on consulted sources instead of citations; shown beside the cited share so "retrieved but not cited" is visible.
- **Citations per answer.** Unique canonical URLs per valid answer (headline); raw citation-block count shown alongside.
- **Concentration.** Top-10 weighted share and the Herfindahl–Hirschman index of weighted share, per model.

### 6.2 Effective date

`effective_date` = the chosen `date_reviewed` if present, else `date_modified`, else `date_published` (§7.3 decides each). Pages without one are **undated**, with the outcome as the logged reason.

### 6.3 Freshness and stale answers (US2, US3)

- **Lag.** lag(url, a) = `answered_at.date − effective_date`, in days. A page whose effective date is after `answered_at` was modified after the model read it: excluded from lag and counted as `modified_after_answer` (H7).
- **Publisher freshness.** Median and interquartile range of lag across that publisher's dated cited URLs, with the count of dated pages.
- **Stale answer, primary.** A valid, time-sensitive answer with at least one dated citation is stale when its **newest** dated citation is older than 365 days: the answer has no fresh source at all.
- **Stale answer, secondary.** At least one dated citation older than 365 days.
- **Undated answers.** Time-sensitive answers with no dated citation are reported as their own count and excluded from both rates.
- **NHS overdue.** Share of cited pages whose `review_due` is before `answered_at`. Reported as a supporting figure.

### 6.4 Overlap (US4)

- **Cross-model overlap.** For each question and run, J(q) = Jaccard(P(Claude), P(GPT)), averaged over questions in an intent. Questions where both answers cite nothing are excluded and counted.
- **Self-overlap ceiling.** For each model, the same Jaccard between run 1 and run 2 answers to the same question.
- **Normalised overlap.** Cross-model overlap ÷ the mean of the two self-overlaps. Near 1 means the models disagree with each other about as much as each disagrees with itself.
- Pooled Jaccard of each model's top-20 publishers per intent is shown for readers who expect it, labelled as pooled.

### 6.5 Stability (US5)

Per model: mean per-question Jaccard between runs (the self-overlap above), and for each top-10 publisher the change in presence share between runs, with a paired bootstrap interval.

### 6.6 Statistics

- **Intervals.** Percentile 95% intervals from a question-cluster bootstrap: 10,000 resamples of the 100 questions, each carrying all its answers (both models, both runs). One seeded resample matrix serves every metric (EvalKit D-37).
- **Model comparisons.** Paired bootstrap of the difference over shared questions; a gap is "separated" only if its p-value survives Holm correction across the top-10 publishers compared. Otherwise it is reported as no clear difference.
- **Small proportions.** The 50-item hand checks use Wilson intervals.
- **Cells under 10 answers** show counts and intervals and are marked directional on the dashboard (H13).
- Float totals use `math.fsum` (EvalKit L-27).
