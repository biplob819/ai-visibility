# Controlling cost

Only `citewatch ask` (and the optional support check) calls a paid API. Fetching, scoring and
reporting are free.

- **Estimate first.** `citewatch ask --run N --dry-run` prints the number of calls and an
  estimate per model before anything is spent. After a smoke run, `scripts/measure_cost.py`
  writes `cost_model.yaml` from the study's own measured usage, and estimates use it.
- **A hard cap.** `max_cost_usd` in `study.yaml` (or `--max-cost`) is enforced before each call;
  a call that could pass the cap is not made.
- **Resume, don't repay.** Answers are stored as they arrive; rerunning a command asks only what
  is missing.
- **What it cost here.** The flagship study's smoke run cost $0.79 and its two runs of 200
  answers each cost $15.03, about 3.8 cents an answer with web search on.
- **Fewer questions or one model** scales the cost down linearly: cost is roughly questions ×
  models × runs × the per-answer price.

Prices live in `prices.yaml` (packaged, with the date they were checked); a study can carry its
own. `citewatch doctor` and the run gate refuse prices more than a week old.
