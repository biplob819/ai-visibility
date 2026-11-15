# Question rubric: UK health and fitness study

Written before any question exists (D-7, QST-01). Every question in `questions.jsonl` must follow it.

## Phrasing rules

1. **Natural UK phrasing.** Write as a UK adult would type into a search box or ask a friend: British spelling (colour, paediatric, haemorrhoids), UK terms (GP, A&E, pharmacist, NHS 111, prescription charge).
2. **No publisher or brand names.** No website, organisation, charity, retailer, product or app names, and no domain names. "NHS" is allowed when the question is about getting care through the NHS ("on the NHS", "NHS 111", "the NHS App"), because that is how people ask; never as a request for a source ("what does the NHS say about…").
3. **One need per question.** No "and also" questions; no lists of sub-questions.
4. **30 words or fewer.**
5. **No leading framing.** Don't hint at an answer or a source ("Is it true that…", "According to…").
6. **No personal data.** No names, places smaller than a nation, or details that identify a person.
7. **Answerable by sourcing.** A good answer cites pages; questions needing a clinical examination ("what is this rash in my photo") are out of scope.

## Intents (20 questions each)

| Intent | Covers |
| --- | --- |
| `symptoms` | What a symptom may mean, when to worry, when to seek care |
| `treatment` | Self-care, over-the-counter and prescribed treatments, what helps |
| `nhs_services` | Access, eligibility, costs, waiting, how to use NHS services |
| `fitness` | Exercise guidance, training, activity levels, injury prevention |
| `nutrition` | Diet, nutrients, supplements, food safety |

## Time-sensitive rule

A question is **time-sensitive** when the correct answer could change within 12 months, because it depends on any of:

- **Services and access:** how to book, which service to use, opening arrangements, digital routes.
- **Eligibility:** who qualifies (vaccines, screening, free prescriptions, schemes).
- **Waiting times or targets.**
- **Prices and charges:** prescription charges, dental bands, eye test costs.
- **Current guidance that is under review or recently changed:** vaccine schedules, screening ages, supplement advice, medicine availability.

Not time-sensitive: stable physiology and long-settled advice ("how much water should adults drink", "what does a stitch while running mean").

Each time-sensitive question carries a `ts_reason` naming the clause above (`services`, `eligibility`, `waiting`, `prices`, `guidance`). At least 8 per intent are time-sensitive.

### Examples

| Question | Time-sensitive | Why |
| --- | --- | --- |
| How much does an NHS prescription cost in England? | Yes | `prices`: the charge is reviewed every year |
| Who can get the flu jab for free this winter? | Yes | `eligibility`: set for each season |
| Why do my legs ache the day after a long run? | No | stable physiology |
| Is it safe to take ibuprofen with paracetamol? | No | long-settled advice |
