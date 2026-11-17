# AI Visibility Report PRD

Nov 14, 2026 · @Biplob Chakraborty

A study of which websites Claude and OpenAI models cite when they answer 100 UK health and fitness questions with web search on, how fresh those pages are, and what a paid freshness and provenance signal would be worth.

## Overview and deliverables

The study shows publishers and AI labs the same thing from two sides: which pages AI answers rest on, and how stale those pages are. That gap is the market for freshness and provenance signals.

**Problem.** Publishers cannot see whether AI answers cite them, or whether those answers rely on outdated pages. AI labs lack reliable freshness and provenance signals for the pages their search tools pull in.

**Goals.**

1. 100 questions across five intents: symptoms, treatment, NHS services, fitness training, nutrition.
2. Answers from Claude Sonnet 5.5 and GPT-6.1 Sol with their web search tools, every citation logged, run twice to measure variance.
3. Publication and modification dates for each cited page, with the source of each date recorded.
4. Citation share by domain, freshness lag, stale-answer rate and model overlap.
5. A one-page spec for a paid freshness and provenance signal.
6. A demo where a reviewer types a domain and sees its AI visibility.
7. An open-source tool, `citewatch`, that anyone can run on their own questions, country and models with their own keys; this study is its flagship run.

**Non-goals.** Crawling at scale; advice on gaming AI answers; judging medical correctness; Google's AI search features.

**Deliverables.**

| Deliverable | What it is | Where it lives |
| --- | --- | --- |
| GitHub repo `ai-visibility` | Runner, citation extractor, polite fetcher, date parser, metrics, tests | GitHub, public |
| Open-source tool `citewatch` | The same pipeline as a package: `pip install citewatch`, `citewatch init`, docs for running your own study | PyPI, MIT licence |
| Findings dashboard | Domain share, freshness lag, overlap by intent, with counts beside every percentage | Cloudflare Pages |
| The post | A blog-style write-up with charts | Project page |
| Signal spec | One page: fields, buyers, delivery, pricing logic | PDF, linked from the project page |
| Demo page | Domain lookup in the shared `portfolio-demos` app | Streamlit Community Cloud |
| Project page and video | The case study in the shared template; a 90-second video | Portfolio site |
| Supporting artifacts | One-page PRD, decision log, data card, "how I built it" note | Repo and project page |

## Personas, user stories and flows

Three personas drive eight stories; the six marked Must make up the first release.

**Personas.**

- **Content lead at a UK health publisher (primary).** Traffic from search is falling and nobody can say whether AI answers cite the site.
- **Data partnerships lead at an AI lab.** Wants to know which sources answers lean on and how stale they are, before paying for any data.
- **Product lead at a web data or infrastructure company.** Wants evidence on both sides of the signals market: what publishers lack and what AI labs would pay for.

**User stories.**

| ID | As a | I want to | So that | Acceptance criteria | Priority |
| --- | --- | --- | --- | --- | --- |
| US1 | Content lead | see my domain's share of citations by intent and model | I know where AI answers use my content | Domain share table per intent and model, with counts | Must |
| US2 | Content lead | see how stale my cited pages are compared with competitors | I know which pages to refresh first | Freshness lag per domain, with the source of each date | Must |
| US3 | Partnerships lead | see how often time-sensitive answers rest on pages not updated in 12 months | I can size the freshness problem | Stale-answer rate per model and intent | Must |
| US4 | Partnerships lead | see how much the two models agree on sources | I know whether one signal serves both | Jaccard overlap of cited domains per intent | Must |
| US5 | Anyone reading | trust the numbers | the findings hold up | Two full runs with variance reported; 50 dates checked against the live pages (for the flagship study agent-checked and owner-approved, OWNER D-63) with an error rate | Must |
| US6 | Product lead | read the main finding and the signal idea in two minutes | I can judge whether the signal is worth building | The post opens with the finding and links the one-page spec | Must |
| US7 | Content lead | type my domain into a demo and see its visibility | I can try it without reading the post | The demo returns a domain card from study data in under a second | Should |
| US8 | Partnerships lead | ask a fresh question and see live citations | I can test beyond the study set | Live mode runs one question on both models behind the passcode | Could |

**Flow A. Run the study (US1 to US5).**

1. `visibility ask --run 1` sends all 100 questions to both models with web search on.
2. `visibility extract` pulls every citation and normalises domains.
3. `visibility fetch` checks robots.txt, fetches each unique cited URL once, and parses dates.
4. `visibility ask --run 2`, then `extract` and `fetch` again for new URLs.
5. `visibility score` computes the metrics and samples 50 citations for EvalKit's support check.
6. `visibility report` builds the dashboard and the post's charts.

**Flow B. Look up a domain (US7).**

1. The reviewer opens the demo page and types a domain, or picks one from the top ten.
2. A domain card shows citation share by model and intent, median freshness lag, the questions that cite it, and the domains cited instead where it is absent.
3. With the passcode, the reviewer can ask a new question and watch both models answer with live citations.

## Requirements

Eleven functional requirements trace to the stories; six non-functional ones set the bars, the most important being a polite fetcher.

**Functional.**

| ID | Requirement | Stories |
| --- | --- | --- |
| FR1 | `questions.jsonl`: 100 questions, 20 per intent, each flagged time-sensitive or not | US1, US3 |
| FR2 | One runner for both models with their native web search tools, at most three searches per answer, an instruction to answer a UK reader in under 150 words with sources | US1 |
| FR3 | A citation extractor for both APIs' formats that keeps URL, title and the quoted span | US1 |
| FR4 | Domain normalisation to the registrable domain | US1, US2 |
| FR5 | A fetcher that honours robots.txt, sends one request per second per domain, times out at 10 seconds and retries at most twice | US2 |
| FR6 | A date parser reading schema.org `dateModified` or `datePublished`, then sitemap `lastmod`, then the HTTP `Last-Modified` header, recording which source each date came from | US2, US5 |
| FR7 | Metrics per model, intent and run: citations per answer, top-10 concentration, freshness lag, stale-answer rate, model overlap | US1 to US4 |
| FR8 | A 50-citation sample scored by EvalKit for whether the page supports the claim | US5 |
| FR9 | A dashboard and post charts with counts beside every percentage | US5, US6 |
| FR10 | A one-page signal spec: fields, buyers, delivery, pricing logic | US6 |
| FR11 | A demo page with domain lookup from study data, plus passcode-protected live questions | US7, US8 |

**Non-functional.**

| ID | Area | Bar |
| --- | --- | --- |
| NFR1 | Politeness | robots.txt honoured; a user agent naming the study and a contact address; only cited URLs fetched |
| NFR2 | Cost | About $12 per run; two runs planned |
| NFR3 | Accuracy | Date parser passes a 20-page test set; the hand check of 50 dates reports its error rate |
| NFR4 | Honesty | The post states on page one that it studies sourcing, not medical accuracy, and that a 100-question sample is directional |
| NFR5 | Speed | Domain lookup in the demo under 1 second |
| NFR6 | Storage | Page bodies are discarded after the support check; only metadata and dates are kept |

## Behavioral spec

The study has three AI-driven parts with rules of their own: the two models answering with web search, the fetcher that dates their sources, and the EvalKit judge that checks support. The rules keep the study fair to the models and polite to the sites it reads.

| ID | Rule | Type | Eval cases |
| --- | --- | --- | --- |
| B1 | Models answer a UK reader in under 150 words and cite their sources, using only their native web search, at most three searches per answer | Must | All 200 answers per run; length, citation count and search-call checks |
| B2 | Citations are taken only from each API's citation fields, never from links typed in the answer text | Must | Extractor tests on both APIs' formats |
| B3 | The fetcher honours robots.txt, fetches only cited URLs, sends one request per second per domain and names the study in its user agent | Must | Fetch log audit; a unit test with a disallowing robots.txt |
| B4 | The judge marks a citation supported only when the page text states the claim | Must | 50-citation sample against your hand labels |
| B5 | The demo's live mode may answer a new question on both models behind the passcode | May | Spend guard test |
| B6 | Present a study answer as medical advice | Never | Page-one statement; the demo shows sourcing, not answer text |
| B7 | Keep page bodies after the support check | Never | Storage audit test |
| B8 | Fetch pages behind logins or paywalls, or retry around a block | Never | Fetch log audit |
| B9 | Advise publishers on gaming AI answers | Never | Review checklist for the post and the demo |

**Good judge output.** {"claim": "Adults should do at least 150 minutes of moderate activity a week.", "verdict": "supported", "rationale": "The cited NHS page states the 150-minute weekly guideline."}

**Bad judge output.** {"claim": "Adults should do at least 150 minutes of moderate activity a week.", "verdict": "supported", "rationale": "The page title mentions exercise."} A title is not evidence, so this breaks B4.

## Trust architecture

A publisher, an AI lab and a data product lead will believe the findings only if the data was collected fairly, every number shows its error, and anyone can rerun the method. Each layer below answers one way a study like this misleads.

| Layer | What it does | Risk it handles | Evidence |
| --- | --- | --- | --- |
| Polite collection | robots.txt honoured, one request per second per domain, a named user agent with a contact address | Harm to the sites studied | Fetch log; user agent string |
| Date provenance | The source of every date recorded, from schema.org to the HTTP header | Wrong freshness numbers | date\_source column; 50 dates checked against the live pages (OWNER D-63) |
| Replication | Two full runs, with variance reported | One run's search results presented as fact | Run-to-run variance table |
| Independent support check | EvalKit's calibrated judge on a 50-citation sample | Weak citations counted as good sourcing | Support rate with hand-label agreement |
| Scope stated up front | Sourcing only, not medical accuracy; 100 questions read as directional | Over-reading the findings | Page-one statement in the post |
| Counts beside percentages | Every share shown with its count | Small samples dressed up as precise | Dashboard and charts |
| Data minimisation | Page bodies discarded after the support check; only metadata kept | Holding publishers' content | Storage audit test |
| Open method | Questions, code and results in a public repo | Claims nobody can check | Public repo |
| Spend guard | Live mode behind a passcode with a daily cap | Abuse of the public demo | Guard tests |

## Wireframe: demo screen

&#91;embedded content: wireframe · demo screen, domain lookup\]

A publisher's first question is "what about my site?", so the demo answers that directly. Lookups read the study's domain cards, which keeps the default view free; live questions sit behind the passcode. The findings dashboard follows the EvalKit layout, with domain share, freshness lag and model overlap in place of the scatter and model table.

## Data flow

&#91;embedded content: data flow · questions to citations to freshness\]

The top row collects citations; the second row dates every cited page and turns both into metrics. Share and overlap need only the citations, while freshness needs the dates. Two checked samples (support: owner-labelled; dates: agent-checked, owner-approved) sit under the metrics so every headline number has an error rate beside it.

## Technical architecture

&#91;embedded content: technical architecture · components, services, hosting\]

- **Package.** Python 3.12 with uv; the anthropic and openai SDKs with their web search tools; `httpx` with a per-domain rate limiter for fetching; `urllib.robotparser` for robots.txt; `extruct` for schema.org JSON-LD; `tldextract` for registrable domains; DuckDB for metrics; EvalKit pinned for the support check.
- **Storage.** Citations and page metadata as JSONL and CSV in the repo; page bodies held in memory only for the 50-citation support check, then discarded.
- **Dashboard, post and demo.** Static HTML on Cloudflare Pages; the demo page in `portfolio-demos` reads `domain_cards.json`, so lookups never call a model.

## Data model and interfaces

Four schemas carry a question from asking to scoring, and one domain card feeds the demo.

```python
class StudyQuestion(BaseModel):
    id: str                          # "v-017"
    text: str
    intent: Literal["symptoms", "treatment", "nhs_services", "fitness", "nutrition"]
    time_sensitive: bool

class Citation(BaseModel):
    question_id: str
    model: Literal["claude-sonnet-5-5", "gpt-6.1-sol"]
    run: int                         # 1 or 2
    url: str
    domain: str                      # registrable domain, e.g. "nhs.uk"
    title: str | None
    quoted_span: str | None
    answered_at: datetime

class PageMeta(BaseModel):
    url: str
    fetched_at: datetime
    status: int | None
    robots_allowed: bool
    date_published: date | None
    date_modified: date | None
    date_source: Literal["schema_org", "meta_tag", "sitemap", "http_header", "none"]
    error: str | None

class DomainCard(BaseModel):         # what the demo shows
    domain: str
    share_by_model: dict[str, float]
    share_by_intent: dict[str, float]
    citations: int
    median_freshness_lag_days: int | None
    questions_citing: list[str]
    cited_instead: list[str]         # domains cited where this one is absent
```

**CLI.**

| Command | What it does |
| --- | --- |
| `visibility ask --run 1` | Asks all questions on both models with web search |
| `visibility extract` | Pulls citations and normalises domains |
| `visibility fetch` | Fetches metadata for new URLs, politely |
| `visibility score` | Computes metrics and runs the support check sample |
| `visibility report` | Builds the dashboard, the post's charts and `domain_cards.json` for the demo |

**Demo functions.** `lookup(domain)` returns a `DomainCard` from `domain_cards.json` with no API calls. `ask_live(question)` runs one question on both models with web search, through the shared spend guard.

## Success metrics, build order and risks

Success is a finding a data product manager would find credible, with its error bars shown, and a signal spec that names a buyer and a unit of value.

**Success metrics.**

| Metric | Definition | Target |
| --- | --- | --- |
| URL date coverage | Share of cited URLs with a resolved date or a logged reason | 90% or more |
| Date accuracy | Agreement with the hand check of 50 dates | Reported, with the error rate |
| Run-to-run variance | Change in domain shares between runs 1 and 2 | Reported per model |
| Support rate | Share of sampled citations where the page supports the claim | Reported per model |
| Signal spec quality | Names buyer, unit of value, delivery and pricing logic on one page | Checked against a data-product checklist: buyer, unit of value, delivery, pricing logic |

**Build order.** No dated milestones. The study is built node by node in dependency order; see the Tech Spec §12.3.

**Risks.**

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Messy metadata gives wrong dates | High | Medium | Record the date source; hand-check 50; report the error rate |
| Search results shift between runs | High | Medium | Two runs, variance reported, findings framed as directional |
| Sites block the fetcher | Medium | Low | Honour robots.txt and log blocked URLs as "no date" rather than forcing access |
| Health answers are read as medical advice | Low | Medium | Page-one statement that the study covers sourcing only |
| The pricing sketch reads as invented numbers | Medium | Medium | Describe the unit of value and tier logic, without price points |

## Sources

Checked on 14 November 2026. EvalKit, which runs the support check, is at [github.com/biplob819/evalkit](https://github.com/biplob819/evalkit).

- [Claude API pricing, including web search](https://platform.claude.com/docs/en/about-claude/pricing)
- [OpenAI API pricing, including web search](https://developers.openai.com/api/docs/pricing.md)
