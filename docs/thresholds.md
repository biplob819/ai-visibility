# Thresholds

A study can state what its results must look like. `citewatch score` checks those rules
after it writes `results/summary.json`, and its exit code tells CI whether they held
(THR-01, OWNER D-65).

| Exit | Meaning |
|---|---|
| 0 | No rules, or every `fail` rule passed. Missed `warn` rules are printed and listed in `--json`. |
| 1 | At least one `fail` rule failed. Each one is printed with its metric, value and bound. |
| 2 | The study or a rule is invalid: an unknown selector, a model or intent the study does not have, or a selector that matches no row of the summary. |

## Writing rules

Add a `thresholds` list to `study.yaml`:

```yaml
thresholds:
  - metric: share:presence:nhs.uk:gpt-6.1-sol:run-1
    op: ">="
    bound: 0.5
    on: lo            # the lower end of the 95% interval must clear the bound
  - metric: coverage
    op: ">="
    bound: 0.9
  - metric: stale:primary:gpt-6.1-sol:all
    op: "<="
    bound: 0.4
    severity: warn    # printed, but the run still exits 0
    name: stale pages stay under 40%
```

| Field | Required | Values |
|---|---|---|
| `metric` | yes | a selector (below) |
| `op` | yes | `">="` or `"<="`. Quote it: an unquoted `>` starts a YAML block scalar. |
| `bound` | yes | a number. Shares and rates are fractions (0.5 is 50%). |
| `on` | no | `point` (default), `lo` or `hi`: which part of the metric's interval is compared. |
| `severity` | no | `fail` (default) or `warn` |
| `name` | no | a label printed beside the selector |

Comparisons are inclusive: `>= 0.5` passes at exactly 0.5. YAML 1.1 reads a bare `on:` key
as the boolean `true`; citewatch reads it as `on`, so you do not need to quote it.

Use `on: lo` for "we are confident it is at least this", and `on: hi` for "we are confident
it is at most this". The point estimate alone can pass or fail by chance on small samples.

## Selectors

Parts are separated by `:`. An intent of `all`, or no intent at all, means the whole study.
Models and intents must be ones the study declares, or the config is refused.

| Selector | Reads from `summary.json` |
|---|---|
| `coverage` | `coverage`: share of cited URLs with a resolved date |
| `share:<kind>:<publisher>:<model>:run-<n>[:<intent>]` | `share` row; kind is `presence`, `weighted` or `consulted` |
| `citations:<model>:run-<n>[:<intent>]` | `citations[].unique_per_answer`: unique cited URLs per answer |
| `concentration:<model>:run-<n>` | `concentration[].top10_share`: share of citations going to the top 10 publishers |
| `stale:<primary\|secondary>:<model>[:<intent>]` | `stale[].rate` |
| `support:<judge>:<model>` | `support[].support_rate` for one judge (`hand` is the owner's labels) |
| `date_accuracy:<source>[:within_7_days\|exact]` | `date_accuracy[]` for a date source (`overall` for all); default `within_7_days` |

`<n>` is 0 (smoke), 1 or 2. A selector that matches no row (for example `run-2` before run 2
is scored, or `date_accuracy:overall` before the hand check) exits 2 rather than passing.

One case is filled in: a `share` selector for a publisher that no answer in that scope cited
reads as 0 (point, lo and hi), with "not cited in this scope" beside it. A rule such as
"our share stays at least 5%" then fails when the site drops out, instead of erroring.

## Examples

```yaml
thresholds:
  # NHS stays the most-cited source in GPT's run-2 answers about symptoms
  - metric: share:presence:nhs.uk:gpt-6.1-sol:run-2:symptoms
    op: ">="
    bound: 0.6
  # fewer than half of Claude's time-sensitive citations are stale (upper bound of the CI)
  - metric: stale:primary:claude-sonnet-5-5:all
    op: "<="
    bound: 0.5
    on: hi
  # the date resolver agrees with the hand check within 7 days at least 60% of the time
  - metric: date_accuracy:overall
    op: ">="
    bound: 0.6
    severity: warn
  # answers carry at least two distinct sources on average
  - metric: citations:gpt-6.1-sol:run-1
    op: ">="
    bound: 2
```

Output when a rule fails:

```
thresholds: 3 of 4 rules pass
  FAIL share:presence:nhs.uk:gpt-6.1-sol:run-2:symptoms: point 0.55 is below the bound >= 0.6 (n=20)
```

With `--json` the payload carries `thresholds` (every rule with its value, `n` and `passed`),
`thresholds_failed` and `thresholds_warned`; `ok` is false only when a `fail` rule failed.

Threshold rules never change what a run measures, so they are left out of the study's
config hash: adding or editing rules between run 1 and run 2 does not trip gate G2.

## In CI

[`examples/github-action/citewatch.yml`](../examples/github-action/citewatch.yml) re-scores a
study from its committed data on every push that touches `studies/` and fails the job when a
`fail` rule fails. It needs no API keys and makes no provider calls or page fetches: `score`
reads only the study's committed `data/` files. Copy it to `.github/workflows/` and set
`STUDY` to your study folder.
