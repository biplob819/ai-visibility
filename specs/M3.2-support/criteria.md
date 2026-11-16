# M3.2 acceptance criteria

**SUP-01** The sample is seeded and stratified (25 per model, 5 per model × intent, 2 reserves per stratum), drawn once before run 1's fetch; replacements follow the reserve order and are logged.
**SUP-02** Claim = the citation's answer span; evidence = the cached main text split into sentences, titles and fragments dropped.
**SUP-03** EvalKit `faithfulness()` at the pinned commit with both judges, live; a contract test pins the imported symbols.
**SUP-04** Body cache and EvalKit store live outside the repo; `--finalise` deletes both and verifies; only verdicts and at most one-sentence quotes are kept.
**SUP-05** Blind labelling sheet (model, verdicts and stratum hidden); support rate per model and judge with Wilson intervals; agreement and Cohen's kappa with intervals.
**SUP-06** The answer-to-fetch gap is recorded per sampled item.
