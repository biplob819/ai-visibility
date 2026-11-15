"""What every answer runner shares: the instruction, the retry policy and the parsed answer
(Tech Spec §3.4, §7.1, ASK-03, ASK-05)."""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from citewatch.schemas import StudyConfig, StudyQuestion

PLACES = {
    "GB": "the UK",
    "US": "the US",
    "IE": "Ireland",
    "IN": "India",
    "CA": "Canada",
    "AU": "Australia",
    "NZ": "New Zealand",
    "DE": "Germany",
    "FR": "France",
    "ES": "Spain",
    "IT": "Italy",
    "NL": "the Netherlands",
    "SG": "Singapore",
    "ZA": "South Africa",
}
TRANSIENT_STATUS = {408, 409, 429}  # plus every 5xx (is_transient)
MAX_ATTEMPTS = 6
T = TypeVar("T")


def instruction(cfg: StudyConfig) -> str:
    """The one instruction both models get (ASK-03). For the flagship it is Tech Spec §7.1's
    text exactly."""
    loc = cfg.user_location
    place = PLACES.get(loc.country) or loc.city or loc.region or loc.country
    return (
        f"Answer for a reader in {place} in under {cfg.word_limit} words. "
        "Use web search to find current sources and cite them."
    )


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class TransportError(RuntimeError):
    """A provider call failed for transient reasons on every attempt."""


def is_transient(exc: BaseException) -> bool:
    """Connection problems, timeouts, rate limits and server-side errors are worth retrying;
    a bad request or an auth failure is not."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in TRANSIENT_STATUS or 500 <= status <= 599
    name = type(exc).__name__
    return name in {"APIConnectionError", "APITimeoutError", "ConnectionError", "TimeoutError"}


def with_retries(
    call: Callable[[], T],
    *,
    attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    stop: Any = None,
) -> T:
    """Exponential backoff with jitter on transient errors, up to `attempts` tries (§3.4).
    A set `stop` event ends the retries at once, so Ctrl-C never waits out a backoff."""
    rng = rng or random.Random()
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not is_transient(exc):
                raise
            if stop is not None and stop.is_set():
                raise TransportError(f"{type(exc).__name__}; stopped before retrying") from exc
            if attempt == attempts:
                raise TransportError(
                    f"{type(exc).__name__} after {attempts} attempts: {exc}"
                ) from exc
            delay = min(60.0, 2 ** (attempt - 1)) + rng.uniform(0, 1)
            if stop is not None:
                if stop.wait(delay):  # Ctrl-C during the backoff: no further request (v5 M1)
                    raise TransportError(f"{type(exc).__name__}; stopped during backoff") from exc
            else:
                sleep(delay)
    raise AssertionError("unreachable")


@dataclass
class Answer:
    """One model's answer to one question, parsed from the raw response(s)."""

    model: str
    model_snapshot: str
    answer_text: str
    stop_reason: str
    refusal: bool
    refusal_category: str | None
    searches: int  # billed searches
    search_actions: list[str]  # every search action the provider reports, in order
    search_errors: list[str]
    tokens_in: int  # includes search-result and cached tokens
    tokens_out: int  # includes reasoning
    cached_in: int
    continuations: int
    raw: list[dict[str, Any]] = field(default_factory=list)  # verbatim responses (D-2)
    request: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawCall:
    """What one call returns before anything is parsed: the request and every verbatim response
    (more than one when a paused turn was continued). `error` is set when a continuation failed
    after some responses were already paid for; those responses are kept (D-2)."""

    model: str
    request: dict[str, Any]
    responses: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class Usage:
    tokens_in: int
    tokens_out: int
    cached_in: int
    searches: int


class Runner(Protocol):
    model: str
    provider: str

    def call(self, question: StudyQuestion, cfg: StudyConfig) -> RawCall: ...

    def usage(self, responses: list[dict[str, Any]]) -> Usage: ...
