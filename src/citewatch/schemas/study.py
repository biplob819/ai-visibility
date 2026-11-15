"""Questions, answers, citations and consulted sources (Tech Spec §4, SCH-01)."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, model_validator

from ._base import (
    HexHash,
    Model,
    ModelId,
    NonBlank,
    NonNegFloat,
    NonNegInt,
    PosInt,
    Run,
    Slug,
    Timestamp,
    canonical_problems,
)

TsReason = Literal["services", "eligibility", "waiting", "prices", "guidance"]
QuestionId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]*-\d{3,}$")]


def count_words(text: str) -> int:
    """Words as the study counts them: whitespace-separated tokens."""
    return len(text.split())


class StudyQuestion(Model):
    id: QuestionId  # "v-017"
    text: NonBlank
    intent: Slug  # checked against StudyConfig.intents by load_questions
    time_sensitive: bool
    ts_reason: TsReason | None = None

    @model_validator(mode="after")
    def _reason_iff_time_sensitive(self) -> StudyQuestion:
        if self.time_sensitive and self.ts_reason is None:
            raise ValueError("a time-sensitive question needs a ts_reason")
        if not self.time_sensitive and self.ts_reason is not None:
            raise ValueError("ts_reason is only for time-sensitive questions")
        return self


class AnswerRecord(Model):
    run: Run
    question_id: QuestionId
    model: ModelId
    model_snapshot: NonBlank
    raw_key: HexHash
    answer_text: str
    word_count: NonNegInt
    over_length: bool
    searches: NonNegInt
    search_errors: tuple[NonBlank, ...] = ()
    refusal: bool
    error: Literal["transport"] | None = None
    tokens_in: NonNegInt
    tokens_out: NonNegInt
    cost_usd: NonNegFloat
    answered_at: Timestamp
    prompt_hash: HexHash
    config_hash: HexHash

    @model_validator(mode="after")
    def _consistent(self) -> AnswerRecord:
        if self.word_count != count_words(self.answer_text):
            raise ValueError(
                f"word_count {self.word_count} does not match the answer text "
                f"({count_words(self.answer_text)} words)"
            )
        if self.refusal and self.error is not None:
            raise ValueError("an answer is a refusal or a transport error, not both")
        return self


def _canonical(url: str) -> str:
    problems = canonical_problems(url)
    if problems:
        raise ValueError(f"url {url!r} is not canonical: {'; '.join(problems)}")
    return url


CanonicalUrl = Annotated[str, Field(min_length=1)]


class Citation(Model):
    run: Run
    question_id: QuestionId
    model: ModelId
    url_raw: NonBlank  # exactly as the API returned it
    url: CanonicalUrl
    host: NonBlank
    publisher: NonBlank  # D-4, e.g. "nhs.uk"
    publisher_group: NonBlank | None = None
    title: str | None = None
    quoted_span: str | None = None  # Claude cited_text; None for OpenAI
    answer_span: NonBlank
    ordinal: PosInt

    @model_validator(mode="after")
    def _url_and_host(self) -> Citation:
        _canonical(self.url)
        if urlsplit(self.url).hostname != self.host:
            raise ValueError(f"host {self.host!r} does not match url {self.url!r}")
        return self


class ConsultedSource(Model):
    run: Run
    question_id: QuestionId
    model: ModelId
    url: CanonicalUrl
    publisher: NonBlank
    page_age: str | None = None  # Claude web_search_result.page_age, verbatim
    cited: bool

    @model_validator(mode="after")
    def _url(self) -> ConsultedSource:
        _canonical(self.url)
        return self
