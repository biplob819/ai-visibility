"""Live mode (DEM-02, DEM-05, US8): one question, both models, the study's §7.1 settings, and
each model's citations only (URL, publisher, quoted span). Never the answer prose (D-17).

Citations come from the API's citation fields through the study's own extractors. The answer
text and the answer spans are dropped here, inside the module, so nothing downstream (the page,
the log, a stored object) ever holds them: `ModelCitations` has no field that could carry them.
For GPT the API gives no quote from the page, so the quoted span is empty; the answer sentence a
citation supports is answer prose and is never shown in its place.

Keys: on the owner's keys the request is held against the owner's daily budget; on a visitor's
own keys (OWNER D-58) it is not, but the passkey, the per-request cap and the rate limit still
apply. A visitor's keys live only in the client objects built for one request; they are never
logged, stored or echoed, and a provider's error message (which can quote part of a key) is
never shown or logged, only its HTTP status.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html import escape
from typing import Any

from citewatch.cost import Price, answer_cost, price_for
from citewatch.demo.guard import GuardRefused, SpendGuard
from citewatch.demo.logs import log_request
from citewatch.extract.extractors import canonical_or_none, extract_claude, extract_openai
from citewatch.extract.urls import publisher_of
from citewatch.runners import Runner
from citewatch.runners.anthropic_runner import MAX_TOKENS
from citewatch.runners.openai_runner import MAX_OUTPUT_TOKENS
from citewatch.schemas import StudyConfig, StudyQuestion, provider_of

MAX_QUESTION_CHARS = 300
MAX_QUOTE_CHARS = 300
BOUND_INPUT_FACTOR = 3  # times the smoke run's measured input tokens per answer
LIVE_QUESTION_ID = "live-001"
NO_QUOTE = "No quote: this provider gives none for its citations."


@dataclass(frozen=True)
class ProviderKeys:
    """API keys for one request. The repr never shows them."""

    anthropic: str = field(default="", repr=False)
    openai: str = field(default="", repr=False)

    def for_provider(self, provider: str) -> str:
        return (self.anthropic if provider == "anthropic" else self.openai).strip()

    def __repr__(self) -> str:
        a = "set" if self.anthropic.strip() else "unset"
        o = "set" if self.openai.strip() else "unset"
        return f"ProviderKeys(anthropic=<{a}>, openai=<{o}>)"


@dataclass(frozen=True)
class LiveCitation:
    url: str
    publisher: str
    quoted_span: str | None  # text from the cited page (Claude's cited_text); None for GPT


@dataclass(frozen=True)
class ModelCitations:
    model: str
    citations: tuple[LiveCitation, ...] = ()
    cost_usd: float = 0.0
    latency_ms: int = 0
    note: str | None = None  # why there are no citations, safe to show


@dataclass(frozen=True)
class LiveResult:
    models: tuple[ModelCitations, ...] = ()
    refused: str | None = None  # safe to show the visitor
    cost_usd: float = 0.0
    bound_usd: float = 0.0


def request_bound_usd(
    cfg: StudyConfig,
    prices: Mapping[str, Price],
    measured: Mapping[str, Mapping[str, int]] | None,
    models: Sequence[str] | None = None,
) -> float:
    """The planning bound for one live question: per model, three times the smoke run's input
    tokens, the runner's whole output ceiling and every allowed search. Held against the
    owner's budget and checked against the per-request cap before any call."""
    total = 0.0
    for m in models if models is not None else cfg.models:
        tokens_in = (measured or {}).get(m, {}).get("tokens_in", 25_000) * BOUND_INPUT_FACTOR
        ceiling = MAX_TOKENS if provider_of(m) == "anthropic" else MAX_OUTPUT_TOKENS
        total += answer_cost(
            price_for(m, prices),
            tokens_in=int(tokens_in),
            tokens_out=ceiling,
            searches=cfg.max_searches,
        )
    return round(total, 6)


def citations_from(model: str, responses: Sequence[Mapping[str, Any]]) -> tuple[LiveCitation, ...]:
    """Each citation the API returned, as URL, publisher and quoted span, in order and without
    repeats. The extractor's answer text and answer spans are discarded here (D-17)."""
    claude = provider_of(model) == "anthropic"
    ex = extract_claude(responses) if claude else extract_openai(responses)
    out: list[LiveCitation] = []
    seen: set[tuple[str, str | None]] = set()
    for c in ex.citations:
        url = canonical_or_none(c.url_raw)
        if url is None:
            continue
        quote = (c.quoted_span or "").strip()[:MAX_QUOTE_CHARS] or None
        if (url, quote) in seen:
            continue
        seen.add((url, quote))
        out.append(LiveCitation(url=url, publisher=publisher_of(url)[0], quoted_span=quote))
    return tuple(out)


def provider_problem(exc: BaseException) -> str:
    """A visitor-safe reason for a failed call: the HTTP status, never the provider's message
    (an auth error can quote part of the key)."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "The provider rejected the API key."
    if status == 429:
        return "The provider is rate-limiting this key; try again later."
    if isinstance(status, int):
        return f"The provider call failed (HTTP {status})."
    return f"The provider call failed ({type(exc).__name__})."


def make_runners(keys: ProviderKeys, models: Sequence[str]) -> dict[str, Runner]:
    """Runners on fresh SDK clients for one request, with the study's own request builders
    (§7.1). Keys pass straight to the clients: never the environment, a file or a log."""
    from citewatch.runners.anthropic_runner import AnthropicRunner
    from citewatch.runners.openai_runner import OpenAIRunner

    out: dict[str, Runner] = {}
    for m in models:
        key = keys.for_provider(provider_of(m))
        if not key:
            continue
        if provider_of(m) == "anthropic":
            import anthropic

            out[m] = AnthropicRunner(m, client=anthropic.Anthropic(api_key=key, max_retries=0))
        else:
            import openai

            out[m] = OpenAIRunner(m, client=openai.OpenAI(api_key=key, max_retries=0))
    return out


def _ask_one(
    model: str,
    runner: Runner,
    question: StudyQuestion,
    cfg: StudyConfig,
    prices: Mapping[str, Price],
    clock: Callable[[], float],
) -> ModelCitations:
    t0 = clock()
    try:
        rc = runner.call(question, cfg)
    except Exception as exc:
        return ModelCitations(
            model, latency_ms=int((clock() - t0) * 1000), note=provider_problem(exc)
        )
    u = runner.usage(rc.responses)
    cost = answer_cost(
        price_for(model, prices),
        tokens_in=u.tokens_in,
        tokens_out=u.tokens_out,
        cached_in=min(u.cached_in, u.tokens_in),
        searches=u.searches,
    )
    cites = citations_from(model, rc.responses)
    note = None
    if rc.error:
        note = "The answer was cut short; these are the citations received."
    elif not cites:
        note = "This answer carried no citations."
    return ModelCitations(model, cites, cost, int((clock() - t0) * 1000), note)


def run_live(
    question: str,
    *,
    identity: str,
    cfg: StudyConfig,
    guard: SpendGuard,
    runners: Mapping[str, Runner],
    prices: Mapping[str, Price],
    measured: Mapping[str, Mapping[str, int]] | None,
    owner_keys: bool,
    clock: Callable[[], float] = time.perf_counter,
) -> LiveResult:
    """The page's live request. `identity` is the signed-in passkey's credential id;
    `runners` are built on the owner's keys (`owner_keys=True`) or the visitor's. Models
    without a runner (no key given) get a note. Logs one aggregate line."""
    t0 = clock()
    mode = "live-owner-keys" if owner_keys else "live-own-keys"
    q = " ".join(question.split())
    keyed = [m for m in cfg.models if m in runners]
    bound = request_bound_usd(cfg, prices, measured, keyed)
    try:
        if not q:
            raise GuardRefused("Type a question.")
        if len(q) > MAX_QUESTION_CHARS:
            raise GuardRefused(f"Keep the question under {MAX_QUESTION_CHARS} characters.")
        if not keyed:
            raise GuardRefused("No API key is available for either model.")
        ticket = guard.reserve(identity, bound, owner_keys=owner_keys)
    except GuardRefused as exc:
        log_request(mode, (clock() - t0) * 1000, 0.0)
        return LiveResult(refused=exc.reason, bound_usd=bound)
    sq = StudyQuestion(id=LIVE_QUESTION_ID, text=q, intent=cfg.intents[0], time_sensitive=False)
    results: dict[str, ModelCitations] = {}
    try:
        with ThreadPoolExecutor(max_workers=len(keyed)) as pool:
            futures = {
                m: pool.submit(_ask_one, m, runners[m], sq, cfg, prices, clock) for m in keyed
            }
            for m, f in futures.items():
                results[m] = f.result()
    finally:
        cost = math.fsum(r.cost_usd for r in results.values())
        # a crash before any cost is known keeps the whole hold (overcount, never under)
        guard.settle(ticket, cost if len(results) == len(keyed) else max(cost, bound))
        log_request(mode, (clock() - t0) * 1000, cost)
    cards = tuple(
        results.get(m) or ModelCitations(m, note=f"No {provider_of(m)} key given.")
        for m in cfg.models
    )
    return LiveResult(models=cards, cost_usd=round(cost, 6), bound_usd=bound)


def live_html(result: LiveResult) -> str:
    """Each model's citations as escaped HTML: URL, publisher and quoted span. There is no
    place for answer prose: `ModelCitations` does not carry it."""
    if result.refused:
        return f"<div class='cw-live'><p class='cw-err'>{escape(result.refused)}</p></div>"
    h = ["<div class='cw-live'>"]
    for mc in result.models:
        n = len(mc.citations)
        h.append(f"<div class='cw-model'><h4>{escape(mc.model)}</h4>")
        h.append(
            f"<p class='cw-meta'>{n} citation{'s' if n != 1 else ''} · ${mc.cost_usd:.4f} · "
            f"{mc.latency_ms / 1000:.1f}s</p>"
        )
        if mc.note:
            h.append(f"<p class='cw-note'>{escape(mc.note)}</p>")
        if mc.citations:
            h.append("<ol class='cw-cites'>")
            for c in mc.citations:
                quote = (
                    f"<blockquote>{escape(c.quoted_span)}</blockquote>"
                    if c.quoted_span
                    else f"<p class='cw-note'>{escape(NO_QUOTE)}</p>"
                )
                h.append(
                    f"<li><b>{escape(c.publisher)}</b> · "
                    f"<a href='{escape(c.url)}' rel='noopener nofollow' target='_blank'>"
                    f"{escape(c.url)}</a>{quote}</li>"
                )
            h.append("</ol>")
        h.append("</div>")
    h.append(f"<p class='cw-meta'>Total cost ${result.cost_usd:.4f}.</p></div>")
    return "".join(h)
