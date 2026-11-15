import math

import pytest
from pydantic import ValidationError

from citewatch.schemas import AnswerRecord, Citation, ConsultedSource, StudyQuestion, count_words

from . import samples as s


def test_valid_records_parse():
    StudyQuestion.model_validate(s.question())
    AnswerRecord.model_validate(s.answer())
    Citation.model_validate(s.citation())
    ConsultedSource.model_validate(s.consulted())


@pytest.mark.parametrize(
    "over",
    [
        {"time_sensitive": True, "ts_reason": None},
        {"time_sensitive": False, "ts_reason": "prices"},
        {"ts_reason": "Not A Slug!"},
        {"id": "V-17"},
        {"intent": "Not A Slug"},
        {"text": "   "},
    ],
)
def test_bad_questions_are_rejected(over):
    with pytest.raises(ValidationError):
        StudyQuestion.model_validate(s.question(**over))


def test_word_count_must_match_the_answer_text():
    with pytest.raises(ValidationError, match="word_count"):
        AnswerRecord.model_validate(s.answer(word_count=3))
    assert count_words("one  two\nthree") == 3


@pytest.mark.parametrize(
    "over",
    [
        {"run": 3},
        {"run": True},
        {"searches": -1},
        {"tokens_in": "21000"},
        {"cost_usd": math.nan},
        {"cost_usd": math.inf},
        {"cost_usd": -0.01},
        {"answered_at": "2026-11-15T10:00:00"},  # naive
        {"model": "llama-3"},  # no supported provider
        {"refusal": True, "error": "transport"},
        {"raw_key": "XYZ"},
    ],
)
def test_impossible_answers_are_rejected(over):
    with pytest.raises(ValidationError):
        AnswerRecord.model_validate(s.answer(**over))


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://WWW.NHS.UK/x", "WWW.NHS.UK"),
        ("https://www.nhs.uk/x#top", "www.nhs.uk"),
        ("ftp://www.nhs.uk/x", "www.nhs.uk"),
        ("https://www.nhs.uk/x", "www.bbc.co.uk"),
    ],
)
def test_citations_need_a_canonical_url_matching_the_host(url, host):
    with pytest.raises(ValidationError):
        Citation.model_validate(s.citation(url=url, host=host))


@pytest.mark.parametrize("over", [{"ordinal": 0}, {"answer_span": ""}, {"extra": 1}])
def test_citation_fields(over):
    with pytest.raises(ValidationError):
        Citation.model_validate(s.citation(**over))


def test_records_are_deeply_immutable_and_hashable():
    a = AnswerRecord.model_validate(s.answer(search_errors=["too_many_requests"]))
    with pytest.raises(ValidationError):
        a.searches = 9  # type: ignore[misc]
    assert isinstance(a.search_errors, tuple)
    hash(a)
