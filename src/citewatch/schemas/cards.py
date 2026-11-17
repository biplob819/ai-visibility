"""Demo domain cards, support verdicts and hand date labels (Tech Spec §4, SCH-04)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import StringConstraints, model_validator

from ._base import SENTENCE_END, FrozenMap, Model, NonBlank, NonNegFloat, NonNegInt
from .summary import Interval

CitationRef = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-2]:[a-z][a-z0-9]*-\d{3,}:(?:claude|gpt)-[a-z0-9.\-]+:[1-9]\d*$"
    ),
]


ImprovementCode = Literal[
    "intent_absent",
    "undated",
    "hidden_date",
    "stale",
    "robots_blocked",
    "robots_unreadable",
    "blocked",
    "not_html",
    "fetch_error",
    "unsupported",
]
SourceFile = Literal[
    "summary.json",
    "answers.jsonl",
    "questions.jsonl",
    "page_meta.jsonl",
    "fetch_log.jsonl",
    "support_verdicts.jsonl",
    "support_labels.jsonl",
]


class Improvement(Model):
    """One reason a publisher is or isn't cited, with a fix and its evidence (OWNER D-65)."""

    code: ImprovementCode
    finding: NonBlank
    fix: NonBlank
    count: NonNegInt
    of: NonNegInt  # the denominator the count is out of
    sources: tuple[SourceFile, ...]  # every file the count and its denominator come from
    examples: tuple[NonBlank, ...] = ()  # up to three URLs or intents behind the count

    @model_validator(mode="after")
    def _counted(self) -> Improvement:
        if self.count == 0 or self.count > self.of:
            raise ValueError("an improvement needs 0 < count <= of")
        if not self.sources:
            raise ValueError("an improvement names the files its numbers come from")
        return self


class DomainCard(Model):
    publisher: NonBlank
    share_by_model: FrozenMap[Interval]
    share_by_intent: FrozenMap[Interval]
    citations: NonNegInt
    answers_citing: NonNegInt
    median_freshness_lag_days: NonNegFloat | None = None
    dated_pages: NonNegInt
    questions_citing: tuple[NonBlank, ...] = ()
    cited_instead: tuple[NonBlank, ...] = ()
    improvement: tuple[Improvement, ...] = ()

    @model_validator(mode="after")
    def _counts(self) -> DomainCard:
        if self.answers_citing > self.citations:
            raise ValueError("answers_citing cannot exceed citations")
        if (self.median_freshness_lag_days is None) != (self.dated_pages == 0):
            raise ValueError("median_freshness_lag_days is set exactly when there are dated pages")
        if self.publisher in self.cited_instead:
            raise ValueError("a publisher cannot be cited instead of itself")
        return self


Quote = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class SupportVerdict(Model):
    citation_ref: CitationRef  # run:question:model:ordinal
    judge: NonBlank
    verdict: Literal["supported", "unsupported"]
    quote: Quote | None = None  # at most one sentence; page text is never kept (NFR6)
    hand_label: Literal["supported", "unsupported"] | None = None

    @model_validator(mode="after")
    def _one_sentence(self) -> SupportVerdict:
        if self.quote is not None and SENTENCE_END.search(self.quote.strip()):
            raise ValueError("a support quote is at most one sentence")
        return self


class HandDateLabel(Model):
    url: NonBlank
    true_modified: dt.date | None = None
    true_published: dt.date | None = None
    not_determinable: bool
    note: str = ""

    @model_validator(mode="after")
    def _undeterminable_has_no_dates(self) -> HandDateLabel:
        has_dates = self.true_modified is not None or self.true_published is not None
        if self.not_determinable and has_dates:
            raise ValueError("a label marked not_determinable has no dates")
        if not self.not_determinable and not has_dates:
            raise ValueError("a label needs a date or not_determinable")
        if self.true_modified and self.true_published and self.true_modified < self.true_published:
            raise ValueError("true_modified is before true_published")
        return self
