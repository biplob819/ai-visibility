"""SUP-02 and SUP-03: the support check's judging adapter (Tech Spec §8.1).

The claim is the citation's `answer_span`; the evidence is the cited page's main text (kept in
the body cache by the fetcher for sampled pages only), split into sentences. Each sampled
citation becomes one EvalKit `FaithfulnessItem`, judged live by both judges through
`evalkit.scorers.faithfulness.faithfulness`, and comes back as one `SupportVerdict` per
(citation, judge). Page text never leaves the body cache: a verdict keeps at most one quoted
sentence (NFR6).

EvalKit is the optional `support` extra, pinned to a commit (D-11). It is imported lazily, so the
sentence splitter and the replacement rule work without it.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from citewatch.fetch.pages import body_cache_dir
from citewatch.schemas import StudyQuestion
from citewatch.schemas._base import SENTENCE_END
from citewatch.schemas.cards import SupportVerdict

if TYPE_CHECKING:
    from evalkit.adapters import ModelAdapter
    from evalkit.cost import CostEstimate, Price
    from evalkit.schemas import RunConfig
    from evalkit.scorers.faithfulness import FaithfulnessItem, FaithfulnessResult

# EvalKit's own defaults: its `evalkit init` config template (onboarding.CONFIG_TEMPLATE) and the
# faithfulness tests use these two judges from different families, and Haiku as the extractor.
DEFAULT_JUDGES: tuple[str, ...] = ("claude-opus-5-5", "gpt-6.1-sol")
DEFAULT_EXTRACTOR = "claude-haiku-5-5"
STORE_DIRNAME = "evalkit-store"
# Planning figure: an answer span is one or two sentences, so fewer claims than EvalKit's
# measured 4.5 per full answer. Replace with the measured mean after the first judged items.
CLAIMS_PER_SPAN = 2.0
QUOTE_MAX = 300  # SupportVerdict.quote's max_length

MIN_WORDS = 4
MIN_CHARS = 20
HEADING_MAX_WORDS = 8
_TERMINAL = re.compile(r"[.!?:;][\"'”’)\]]*$")
_SPLIT = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_ABBREV = frozenset(
    {"mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc", "inc", "ltd", "co"}
    | {"corp", "no", "fig", "e.g", "i.e", "approx", "dept", "est", "u.s", "u.k"}
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


# ---- SUP-02: claim and evidence ----------------------------------------------------------------


def _looks_like_heading(line: str) -> bool:
    """A title, heading, menu or label: no terminal punctuation and either short or mostly
    capitalised words. A title is not evidence (§8.1 step 4)."""
    if _TERMINAL.search(line):
        return False
    words = _WORD.findall(line)
    if len(line.split()) <= HEADING_MAX_WORDS:
        return True
    capped = sum(w[0].isupper() for w in words)
    return bool(words) and capped / len(words) >= 0.7


def _split_line(line: str) -> list[str]:
    out: list[str] = []
    start = 0
    for m in _SPLIT.finditer(line):
        head = line[start : m.start()]
        last = head.rsplit(None, 1)[-1].rstrip(".!?\"'”’)]").casefold() if head.strip() else ""
        if last in _ABBREV or (len(last) == 1 and last.isalpha()):  # "Dr. Smith", "J. Doe"
            continue
        out.append(head)
        start = m.end()
    out.append(line[start:])
    return [s.strip() for s in out if s.strip()]


def evidence_sentences(text: str) -> tuple[str, ...]:
    """The page's main text as evidence sentences: one line at a time, headings and titles
    dropped, each remaining line split into sentences, fragments under 4 words or 20
    characters dropped. Order is kept (EvalKit cites sentence i as i, 1-based)."""
    out: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or _looks_like_heading(line):
            continue
        for s in _split_line(line):
            if len(s) >= MIN_CHARS and len(s.split()) >= MIN_WORDS:
                out.append(s)
    return tuple(out)


def text_path(url: str, cache_dir: Path) -> Path:
    """Where the fetcher's `keep_text` wrote this page's main text (fetch/pages.py)."""
    return cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".txt")


def cached_sentences(url: str, cache_dir: Path) -> tuple[str, ...]:
    """The page's evidence sentences, or () when no text was cached or none survives."""
    p = text_path(url, cache_dir)
    if not p.is_file():
        return ()
    return evidence_sentences(p.read_text(encoding="utf-8"))


def item_id(citation_ref: str) -> str:
    """EvalKit item ids cannot contain ':'; no part of a citation ref contains '_'."""
    return citation_ref.replace(":", "_")


def ref_of(item_id: str) -> str:
    return item_id.replace("_", ":")


# ---- SUP-01: the replacement rule --------------------------------------------------------------


def replacements(
    sample_rows: Sequence[dict[str, Any]],
    ok_urls: Collection[str],
    *,
    cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The §8.1 replacement rule. A sampled citation whose page did not fetch `ok` (its URL is
    not in `ok_urls`) or, when `cache_dir` is given, has no usable cached text, is replaced by
    the next unused reserve of its stratum in rank order; a reserve that fails the same test is
    skipped. When a stratum runs out of reserves it stays short.

    Returns (final rows, log). Final rows keep stratum order (model, intent) and each stratum's
    rank order, a replacement taking the slot of the citation it replaces and carrying
    `replaces`. Each log entry names the stratum, the replaced ref, the reason, the reserve
    used (`by`, None when none was left) and the reserves skipped."""

    def reason(row: dict[str, Any]) -> str | None:
        if row["url"] not in ok_urls:
            return "fetch not ok"
        if cache_dir is not None and not cached_sentences(row["url"], cache_dir):
            return "no cached text"
        return None

    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sample_rows:
        strata[(r["model"], r["intent"])].append(r)
    final: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    for (model, intent), rows in sorted(strata.items()):
        rows = sorted(rows, key=lambda r: r["rank"])
        reserves = iter([r for r in rows if r["role"] == "reserve"])
        for row in (r for r in rows if r["role"] == "sample"):
            why = reason(row)
            if why is None:
                final.append(dict(row))
                continue
            skipped: list[str] = []
            by = None
            for res in reserves:
                if reason(res) is None:
                    by = res
                    break
                skipped.append(res["citation_ref"])
            if by is not None:
                final.append({**by, "replaces": row["citation_ref"]})
            log.append(
                {
                    "model": model,
                    "intent": intent,
                    "replaced": row["citation_ref"],
                    "reason": why,
                    "by": None if by is None else by["citation_ref"],
                    "skipped": skipped,
                }
            )
    return final, log


# ---- SUP-03: EvalKit items, judging and verdicts -----------------------------------------------


def items_for(
    sample_rows: Sequence[dict[str, Any]],
    citations: Sequence[dict[str, Any]],
    questions: Sequence[StudyQuestion],
    cache_dir: Path,
) -> list[FaithfulnessItem]:
    """One `FaithfulnessItem` per row with role `sample` or a reserve promoted by
    `replacements` (it carries `replaces`); other reserves are ignored. `question` is the study
    question, `explanation` the citation's answer span, `evidence` the cached page sentences.

    A row with no cached text (or none that survives the splitter) gets no item: it needs its
    reserve, so run `replacements(..., cache_dir=...)` first and pass its final rows."""
    from evalkit.scorers.faithfulness import FaithfulnessItem

    from .sample import citation_ref

    by_ref = {citation_ref(c): c for c in citations}
    text_of = {q.id: q.text for q in questions}
    out: list[FaithfulnessItem] = []
    for row in sample_rows:
        if row["role"] != "sample" and not row.get("replaces"):
            continue
        evidence = cached_sentences(row["url"], cache_dir)
        if not evidence:
            continue
        cit = by_ref[row["citation_ref"]]
        out.append(
            FaithfulnessItem(
                id=item_id(row["citation_ref"]),
                question=text_of[cit["question_id"]],
                explanation=cit["answer_span"],
                evidence=evidence,
            )
        )
    return out


def one_sentence(text: str) -> str | None:
    """`text` cut at its first sentence end and to the quote limit; None when empty."""
    s = " ".join(text.split())
    m = SENTENCE_END.search(s)
    if m:
        s = s[: m.start() + 1]
    if len(s) > QUOTE_MAX:
        s = s[: QUOTE_MAX - 1].rstrip() + "…"
    return s or None


class SupportJudgingIncomplete(RuntimeError):
    """Some items were not fully judged (transport error, unfinished batch or judge failure)."""

    def __init__(self, refs: Sequence[str]) -> None:
        self.refs = tuple(refs)
        super().__init__(
            f"{len(refs)} item(s) not fully judged: {', '.join(refs[:5])}; rerun (judged claims "
            "are cached and not paid again) or pass strict=False to count them unsupported"
        )


def verdicts_for(
    items: Sequence[FaithfulnessItem],
    results: Sequence[FaithfulnessResult],
    judges: Sequence[str],
    *,
    strict: bool = True,
) -> list[SupportVerdict]:
    """One `SupportVerdict` per (citation, judge).

    Rule: a citation is `supported` by a judge only if the span yielded at least one claim and
    that judge judged every claim `supported`; anything else (an unsupported claim, a claim the
    judge failed on, no claims extracted) is `unsupported`. With `strict`, an item that was not
    fully judged raises `SupportJudgingIncomplete` instead of being coded unsupported.

    The quote is kept only for a supported verdict: the first evidence sentence the judge cited
    for the first claim, cut to one sentence."""
    by_id = {i.id: i for i in items}
    if strict:
        bad = [
            ref_of(r.id)
            for r in results
            if r.extraction_error is not None
            or any(r.judge_errors.get(j, 0) or r.pending.get(j, 0) for j in judges)
        ]
        if bad:
            raise SupportJudgingIncomplete(bad)
    out: list[SupportVerdict] = []
    for r in results:
        item = by_id[r.id]
        for j in judges:
            ok = bool(r.claims) and all(c.verdicts.get(j) == "supported" for c in r.claims)
            quote = None
            if ok:
                nums = next((c.evidence.get(j, ()) for c in r.claims if c.evidence.get(j)), ())
                if nums and 1 <= nums[0] <= len(item.evidence):
                    quote = one_sentence(item.evidence[nums[0] - 1])
            out.append(
                SupportVerdict(
                    citation_ref=ref_of(r.id),
                    judge=j,
                    verdict="supported" if ok else "unsupported",
                    quote=quote,
                )
            )
    return out


def _repo_root() -> Path | None:
    root = Path(__file__).resolve().parents[3]
    return root if (root / "pyproject.toml").is_file() else None


def default_store_dir() -> Path:
    """EvalKit's store sits inside the body cache, so `--finalise` deletes both at once."""
    return body_cache_dir() / STORE_DIRNAME


def run_config(
    judges: Sequence[str] = DEFAULT_JUDGES,
    extractor: str = DEFAULT_EXTRACTOR,
    *,
    max_cost_usd: float | None = None,
) -> RunConfig:
    from evalkit.schemas import RunConfig

    # `models` is required but unused by faithfulness(); efforts are explicit (EvalKit D-24).
    return RunConfig(
        models=(extractor,),
        judges=tuple(judges),
        extractor=extractor,
        max_cost_usd=max_cost_usd,
        judge_effort="medium",
        extractor_effort="medium",
    )


async def judge(
    items: Sequence[FaithfulnessItem],
    *,
    judges: Sequence[str] = DEFAULT_JUDGES,
    store_dir: Path | None = None,
    extractor: str = DEFAULT_EXTRACTOR,
    adapters: Mapping[str, ModelAdapter] | None = None,
    prices: dict[str, Price] | None = None,
    max_cost_usd: float | None = None,
    strict: bool = True,
) -> list[SupportVerdict]:
    """Judge every item live with each judge and map the results to `SupportVerdict`s
    (see `verdicts_for` for the rule). EvalKit's store is `store_dir` (default: inside the body
    cache), which must be outside the repository. `adapters` defaults to EvalKit's real
    Anthropic and OpenAI adapters, which spend money; `max_cost_usd` caps the executor."""
    from evalkit.adapters import get_adapter
    from evalkit.cost import load_prices
    from evalkit.pipeline.generate import adapter_key, provider_for
    from evalkit.runtime import Executor, Store
    from evalkit.scorers.faithfulness import faithfulness

    store = (store_dir or default_store_dir()).resolve()
    root = _repo_root()
    if root is not None and store.is_relative_to(root.resolve()):
        raise ValueError(f"the EvalKit store {store} must be outside the repository (NFR6)")
    config = run_config(judges, extractor, max_cost_usd=max_cost_usd)
    prices = prices if prices is not None else load_prices()
    if adapters is None:
        keys = {adapter_key(provider_for(m), m) for m in (extractor, *judges)}
        adapters = {k: get_adapter(k, prices=prices) for k in keys}
    executor = Executor(
        Store(store), concurrency=dict(config.concurrency), max_cost_usd=max_cost_usd
    )
    results = await faithfulness(
        items,
        executor=executor,
        config=config,
        adapters=adapters,
        prices=prices,
        judges=tuple(judges),
        live=True,
        run_id="citewatch-support",
    )
    return verdicts_for(items, results, judges, strict=strict)


# ---- cost estimate (Tech Spec §10: support = Σ_judges n × (t_ev × p_in + t_v × p_out)) ---------


def _estimate(
    rows: Sequence[tuple[int, int]],
    judges: Sequence[str],
    extractor: str,
    claims_per_span: float,
    prices: dict[str, Price] | None,
) -> CostEstimate:
    """rows: (extractor prompt tokens, judge prompt tokens per claim) per item. Live prices,
    no batch discount; outputs from EvalKit's measured TokenAssumptions."""
    import math

    from evalkit.cost import CostEstimate, CostLine, TokenAssumptions, call_cost, load_prices

    prices = prices if prices is not None else load_prices()
    a = TokenAssumptions()
    ext_price = prices[extractor]
    ext_usd = sum(
        call_cost(ext_price, tokens_in=t, tokens_out=a.t_ext_out, tokens_reasoning=a.t_ext_reason)
        for t, _ in rows
    )
    lines = [CostLine(node="extract", model=extractor, calls=len(rows), usd=ext_usd)]
    for j in judges:
        price = prices[j]
        usd = sum(
            claims_per_span
            * call_cost(price, tokens_in=t, tokens_out=a.t_j_out, tokens_reasoning=a.t_j_reason)
            for _, t in rows
        )
        calls = math.ceil(claims_per_span * len(rows))
        lines.append(CostLine(node="judge", model=j, calls=calls, usd=usd))
    return CostEstimate(lines=tuple(lines), total_usd=sum(x.usd for x in lines))


def estimate_cost(
    items: Sequence[FaithfulnessItem],
    *,
    judges: Sequence[str] = DEFAULT_JUDGES,
    extractor: str = DEFAULT_EXTRACTOR,
    claims_per_span: float = CLAIMS_PER_SPAN,
    prices: dict[str, Price] | None = None,
) -> CostEstimate:
    """Expected cost of judging these items, from their actual text, before any spend. Every
    claim is judged against all of its item's evidence (EvalKit FTH-02)."""
    from evalkit.cost import estimate_tokens
    from evalkit.pipeline.extract import EXTRACTOR_PROMPT
    from evalkit.pipeline.judge import JUDGE_RUBRIC, SENTENCE_FORMAT

    rows = []
    for it in items:
        cites = str(list(range(1, len(it.evidence) + 1)))
        ext = estimate_tokens(EXTRACTOR_PROMPT, it.question, it.explanation, cites)
        lines = [SENTENCE_FORMAT.format(n=n, text=s) for n, s in enumerate(it.evidence, 1)]
        # a claim is part of the span: the whole span is an upper bound on its length
        rows.append((ext, estimate_tokens(JUDGE_RUBRIC, it.explanation, *lines)))
    return _estimate(rows, judges, extractor, claims_per_span, prices)


def planning_estimate(
    n_items: int = 50,
    *,
    evidence_tokens: int = 2000,
    span_tokens: int = 60,
    question_tokens: int = 25,
    judges: Sequence[str] = DEFAULT_JUDGES,
    extractor: str = DEFAULT_EXTRACTOR,
    claims_per_span: float = CLAIMS_PER_SPAN,
    prices: dict[str, Price] | None = None,
) -> CostEstimate:
    """The same estimate from token counts alone, for the CLI to print before items exist."""
    from evalkit.cost import estimate_tokens
    from evalkit.pipeline.extract import EXTRACTOR_PROMPT
    from evalkit.pipeline.judge import JUDGE_RUBRIC

    ext = estimate_tokens(EXTRACTOR_PROMPT) + question_tokens + span_tokens
    jud = estimate_tokens(JUDGE_RUBRIC) + span_tokens + evidence_tokens
    return _estimate([(ext, jud)] * n_items, judges, extractor, claims_per_span, prices)
