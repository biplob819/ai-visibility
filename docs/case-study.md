# citewatch: what AI search cites, and how fresh it is

AI search answers now send readers to sources, but nobody could say which ones, or whether
those pages are current. I built citewatch, an open-source tool that asks AI models questions
with web search on, records every citation, visits each cited page politely to date it, and
reports who gets cited with counts and 95% intervals. Its first study asked Claude Sonnet 5.5
and GPT-6.1 Sol 100 pre-registered UK health questions, twice. GPT cited nhs.uk in 83% of
answers, Claude in 10%; the two models' sources overlapped by only 10% per question; and 43%
of GPT's time-sensitive answers rested on no dated source under a year old, against 12% of
Claude's. The study cost $15.03 in API calls. It ships with a dashboard, a write-up, a one-page
signal spec for a data product, domain cards that tell each cited publisher what would make
its pages readable and current, and a passkey-protected demo.

## My role

Product and engineering, end to end: framed the question and the buyer, wrote the PRD and
technical spec, pre-registered the questions and metrics before any answer was seen, built the
tool and its statistics, ran the study within an owner-approved budget, and shipped the
dashboard, post, signal spec, demo and open-source release. Built with Claude Code under a
node-by-node harness in which every capability needed passing tests and an independent,
skeptical review before it counted as done.

## Key decisions

1. **Pre-register, then publish every deviation.** Questions, settings, seeds and metric
   definitions were frozen and hashed before run 1; each later change is listed with its
   decision and effect. *Trade-off:* slower to start and no tuning after seeing results, in
   exchange for numbers a skeptical reader can trust.
2. **Measure sourcing, never medical accuracy, and show the checks.** Every share carries its
   count and interval; a support check (two AI judges plus a human check) and a held-out date
   check sit beside the headlines, including where they disagree. *Trade-off:* a narrower claim
   and less dramatic headlines, but none that overreach.
3. **Polite by construction.** citewatch obeys robots.txt at one request per second per host,
   never stores page bodies, and gives publishers only readability advice (a visible, marked-up
   date; a readable robots.txt), never tips for gaming AI answers. *Trade-off:* 221 of 841
   cited URLs ended up with no usable date, 88 of them because the page could not be read at
   all; the study reports this rather than working around it.

**Links:** [repository](https://github.com/biplob819/ai-visibility) ·
[dashboard](https://biplob819.github.io/ai-visibility/) ·
[post](https://biplob819.github.io/ai-visibility/post/) ·
[demo](https://citewatch.streamlit.app) ·
[signal spec](https://github.com/biplob819/ai-visibility/blob/main/docs/signal-spec.pdf)
