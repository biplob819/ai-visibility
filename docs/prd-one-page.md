# citewatch: one-page PRD

**Problem.** AI search answers now point readers to sources, but publishers cannot see whether
they are cited or whether the answers rest on outdated pages, and AI labs lack a reliable
freshness and provenance signal for the pages their search tools pull in.

**Who it is for.** Publishers and content teams (am I cited, and is my page readable and
current?); AI search and data teams (which sources do answers rest on, and how fresh?);
researchers who want to rerun the measurement on their own questions.

**What it does.** Asks AI models a fixed set of questions with web search on, records every
citation from the APIs' citation fields, fetches each cited page politely to find when it was
last updated, and reports citation share, freshness, staleness and model overlap with counts
and 95% intervals, plus a card per publisher saying what would make its pages readable and
current.

**Scope of the first study.** 100 pre-registered UK health and fitness questions in five
intents, asked of Claude Sonnet 5.5 and GPT-6.1 Sol, twice.

**Non-goals.** Judging medical correctness; advice on gaming AI answers; crawling at scale;
Google's AI search features.

**Success measures.** Every headline number traceable to stored data with a count and
interval; date coverage of at least 90% of cited URLs (reached 89%, reported as below target);
a held-out date check and a support check reported beside the findings; a study cost inside
the approved budget; a newcomer gets an example report in under five minutes with no keys.

**Deliverables.** The open-source tool on PyPI; the public repository with the study's data
and results; the [dashboard](https://biplob819.github.io/ai-visibility/), the
[post](https://biplob819.github.io/ai-visibility/post/) and a one-page
[signal spec](signal-spec.pdf); a demo for domain lookup with a passkey-protected live mode;
thresholds that fail a CI job when a metric crosses a bound.

**Constraints.** Obey robots.txt and a fixed politeness floor; never store page bodies; a hard
cost cap per run and a $45 budget for the whole study ($38
approved for the two study runs); the pre-registration frozen before the first
answer.

**Key risks and how they were handled.** Date parsing could be wrong: seven sources, explicit
plausibility rules, and a held-out check on pages the parser was never tuned on. Citations
might not support the claims: two AI judges and a human check, reported with their
disagreement. Results might not hold: two runs, question-cluster bootstrap intervals and Holm
correction, and every finding labelled directional.

The full PRD and technical spec are in the repository root.
