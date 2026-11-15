# N1.4 acceptance criteria

**QST-01** `RUBRIC.md` exists, was committed before `questions.jsonl`, and states the phrasing rules and the time-sensitive rule with examples of each.
**QST-02** `questions.jsonl` has 100 questions, 20 per declared intent, at least 8 time-sensitive per intent, each time-sensitive question with a `ts_reason`; the lint rejects a duplicate id, an undeclared intent, more than 30 words, a domain name or a listed publisher name.
**QST-03** `preregistration.md` contains Tech Spec §6 verbatim, the seeds and the exclusions; its sha256 and the questions' sha256 are recorded in `decisions.md`; the data-freeze test fails when either file changes.
**QST-04** `DATA_CARD.md` covers collection, discarding, politeness, quoted spans and limits, and states nothing as done that a later node has not yet built.
