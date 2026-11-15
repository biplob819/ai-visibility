import pytest
from pydantic import ValidationError

from citewatch.schemas import (
    DomainCard,
    HandDateLabel,
    Interval,
    OverlapRow,
    StudySummary,
    SupportVerdict,
)

from . import samples as s


def test_valid_summary_and_cards_parse():
    StudySummary.model_validate(s.summary())
    DomainCard.model_validate(s.card())
    SupportVerdict.model_validate(s.verdict())
    HandDateLabel.model_validate(s.hand_label())


@pytest.mark.parametrize(
    "bad",
    [
        s.interval(point=0.6, hi=0.5),
        s.interval(lo=0.5, point=0.4),
        s.interval(k=101, n=100),
        s.interval(n=-1),
        {**s.interval(), "point": float("nan")},
    ],
)
def test_interval_rules(bad):
    with pytest.raises(ValidationError):
        Interval.model_validate(bad)


@pytest.mark.parametrize(
    "over",
    [
        {"schema_version": "2.0"},
        {"runs": []},
        {"runs": [2, 1]},
        {"runs": [1, 1]},
        {"runs": [3]},
        {"questions_sha256": "abc"},
        {"preregistration_sha256": "G" * 64},
    ],
)
def test_summary_rules(over):
    with pytest.raises(ValidationError):
        StudySummary.model_validate(s.summary(**over))


def test_summary_requires_schema_version():
    d = s.summary()
    del d["schema_version"]
    with pytest.raises(ValidationError):
        StudySummary.model_validate(d)


def test_overlap_model_only_for_self():
    with pytest.raises(ValidationError):
        OverlapRow.model_validate(
            {
                "intent": None,
                "run": 1,
                "kind": "cross_model",
                "model": "gpt-6.1-sol",
                "value": s.interval(),
            }
        )


@pytest.mark.parametrize(
    "quote",
    ["First sentence. Second sentence.", "x" * 301, "Stop! Then more."],
)
def test_support_quote_is_one_sentence(quote):
    with pytest.raises(ValidationError):
        SupportVerdict.model_validate(s.verdict(quote=quote))


def test_support_quote_allows_abbreviation_free_single_sentence():
    assert SupportVerdict.model_validate(s.verdict(quote="Adults need 150 minutes a week."))


def test_hand_label_rules():
    with pytest.raises(ValidationError):
        HandDateLabel.model_validate(s.hand_label(not_determinable=True))
    with pytest.raises(ValidationError):
        HandDateLabel.model_validate(s.hand_label(true_modified=None))
    ok = s.hand_label(true_modified=None, not_determinable=True)
    assert HandDateLabel.model_validate(ok).not_determinable


@pytest.mark.parametrize(
    "over",
    [{"answers_citing": 121}, {"cited_instead": ["nhs.uk"]}, {"dated_pages": 0}],
)
def test_domain_card_rules(over):
    with pytest.raises(ValidationError):
        DomainCard.model_validate(s.card(**over))


def test_maps_are_frozen():
    c = DomainCard.model_validate(s.card())
    with pytest.raises(TypeError):
        c.share_by_model["x"] = c.share_by_model["claude-sonnet-5-5"]  # type: ignore[index]
    hash(c)
