# Run your own study

A study is a folder with `study.yaml`, `questions.jsonl`, a rubric and, once it runs, its data
and results. Paid steps need the provider SDKs (`pip install 'citewatch[anthropic,openai]'` or
`uv sync --extra anthropic --extra openai`) and your API keys in the study's `.env`.

## 1. Create the folder

```bash
citewatch init my-study --contact https://your-site.example/about
```

`init` writes `study.yaml`, `questions.jsonl`, `RUBRIC.md` and `.env.example`, and never
overwrites a file. `--contact` goes into the user agent every fetch sends, so site owners can
reach you; placeholders such as example.org are refused.

## 2. Settings (`study.yaml`)

| Field | What it sets |
|---|---|
| `name` | the study's id (lower case, digits, dashes) |
| `intents` | the topics your questions fall into; each question names one |
| `ts_reasons` | your rubric's reasons a question is time-sensitive (services, prices, …) |
| `models` | `claude-*` and `gpt-*` models with web search; one provider is fine |
| `effort`, `max_searches`, `word_limit` | how each model answers (kept identical across models) |
| `user_location` | `country` (ISO code), optional `city`, `region`, `timezone`: where searches run from |
| `stale_days` | how old a source must be to count as stale (365 in the flagship study) |
| `seeds` | fixed seeds for question order, samples and the bootstrap |
| `max_cost_usd` | a hard cap per command; a run stops rather than overspend |
| `thresholds` | optional rules that fail CI ([thresholds](thresholds.md)) |

## 3. Questions (`questions.jsonl`)

One JSON object per line:

```json
{"id": "q-001", "text": "How do I treat a burn from boiling water?", "intent": "symptoms", "time_sensitive": false}
{"id": "q-002", "text": "Who can get the flu jab for free this winter?", "intent": "treatment", "time_sensitive": true, "ts_reason": "services"}
```

Ids are unique; every `intent` is in `study.yaml`; a time-sensitive question names its
`ts_reason`. Write questions as a person would ask them, without naming a source. `citewatch
doctor` checks the folder.

## 4. Run it

```bash
citewatch doctor --study my-study                 # keys, SDKs, prices, user agent
citewatch ask --run 0 --dry-run --study my-study  # cost estimate, no calls
citewatch ask --run 0 --study my-study            # paid smoke run
python scripts/measure_cost.py my-study --run 0   # from a clone: writes cost_model.yaml
```

Then freeze the study before its real runs: write `preregistration.md` (your questions'
purpose, settings, seeds and metric definitions), record its sha256 and that of
`questions.jsonl` in a `decisions.md`, and commit. `citewatch ask --run 1 --dry-run` lists
anything the run gate still needs; it refuses a dirty or non-git folder, an estimate over the
cap, or prices more than a week old. Run 2 must start at least two hours after run 1 ends, with
the runner and extractor code unchanged.

```bash
citewatch ask --run 1 --study my-study
citewatch ask --run 2 --study my-study     # two hours later
citewatch extract --study my-study
citewatch fetch --study my-study
citewatch score --study my-study
citewatch report --study my-study --title "my topic"
```

`score` writes `results/summary.json`, `domain_cards.json` and, if the support check ran,
`calibration.json`; `report` writes `results/site/index.html` and the post beside it.
