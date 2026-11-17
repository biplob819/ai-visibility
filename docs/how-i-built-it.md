# How I built it

citewatch went from PRD to a released study in three days (15–17 November 2026), built with
Claude Code. This note covers how the work was organised and what the process caught. It is a
companion to the [PRD](prd-one-page.md), the [decision log](decisions.md) and the
[lessons](lessons.md).

## A plan as a graph, not a to-do list

The PRD and technical spec became 21 **nodes** (runner, extractor, fetcher, date resolver,
metrics, support check, dashboard, post, release and so on) covering 110 numbered
**capabilities** in [`docs/graph/catalog.tsv`](graph/catalog.tsv). Each node has a spec,
acceptance criteria, tasks and a running log under `specs/`. A node could start only when the
nodes it depended on were done, and parallel lanes in separate git worktrees built independent
nodes at the same time.

## Done means proved, then disproved

Every capability needed five kinds of proof, each a named test or a stated reason it does not
apply: the logic itself, its contract (schemas, CLI, provider formats), a golden replay, a
reproducibility check and a safety check. Twelve gates had to pass twice: the node's claims
and eligibility, every proof present and not skipped, lint, types, the full test suite, a
golden run on the oldest supported Python, politeness, safety (a secret scan and an audit for
stored page bodies), a build smoke test, tests for every changed file, and complete records.

Then a fresh agent that had not built the node tried to **disprove** it, with no access to the
builder's reasoning, only the repository. A node was done only when every criterion was
confirmed and no high or medium finding was open. Nodes took one to five review passes. Among
the reviews' finds:

- a PyPI upload that would have failed after the tag, because an optional dependency pointed at
  a git commit;
- the full-history audit flagging its own test file once that file was committed (lesson L-38);
- a demo page where a visitor's blank API key could have fallen back to the owner's, which the
  code handled but no test proved;
- sentences in the publisher report and the post that claimed more than citewatch saw, while
  every number was right (lesson L-39).

## The study was frozen before any answer

The questions, settings, seeds and metric definitions were written into a pre-registration and
hashed before run 1. The run gate refuses a study whose frozen files changed, whose estimate
exceeds the cap or whose prices are stale. Everything decided afterwards is in the
[deviations record](deviations.md) with its decision and its effect on the numbers.

## The owner decided; the agent recorded

Choices that changed scope, cost or what the study claims went to the owner as a question with
options, and each answer became a numbered decision (84 in all, `OWNER D-…` for the owner's
own). Examples: hosting the dashboard on GitHub Pages, approving the post against the
responsible-publishing checklist, and having a fresh agent check held-out dates with the owner
approving, disclosed wherever the result appears. Spending had a hard budget ($45) and every
paid run its own approval; the two study runs cost $15.03.

## What I would keep

- **A skeptical reviewer that never saw the build.** Most of what it found was invisible from
  inside: claims, not code.
- **Proofs named in a catalog.** "Tested" stops being a feeling when each requirement points at
  a test that must not be skipped.
- **Lessons as rules.** Each of the 39 lessons states what to do next time, such as committing
  before running a history audit, and the next node applied it.
