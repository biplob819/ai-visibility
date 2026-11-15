import pytest
from pydantic import ValidationError

from citewatch.schemas import DateCandidate, PageMeta

from . import samples as s


def test_valid_page_parses_with_review_date_as_effective():
    p = PageMeta.model_validate(s.page())
    assert str(p.effective_date) == "2026-02-01" and p.effective_source == "visible_text"


@pytest.mark.parametrize(
    "over",
    [
        {"source": "rumour"},
        {"kind": "updated"},
        {"evidence": "x" * 121},
        {"evidence": ""},
    ],
)
def test_candidate_vocabulary(over):
    with pytest.raises(ValidationError):
        DateCandidate.model_validate(s.candidate(**over))


def test_outcome_vocabulary_and_ok_needs_fetch_details():
    with pytest.raises(ValidationError):
        PageMeta.model_validate(s.page(outcome="hacked"))
    with pytest.raises(ValidationError, match="fetched_at and status"):
        PageMeta.model_validate(s.page(fetched_at=None))
    with pytest.raises(ValidationError, match="HTTP status"):
        PageMeta.model_validate(s.page(status=999))


def test_chosen_dates_must_be_backed_by_a_non_rejected_candidate():
    with pytest.raises(ValidationError, match="not backed"):
        PageMeta.model_validate(s.page(date_modified="2026-11-15", modified_source="http_header"))
    with pytest.raises(ValidationError, match="not backed"):
        PageMeta.model_validate(s.page(modified_source="meta_tag"))
    with pytest.raises(ValidationError, match="set together"):
        PageMeta.model_validate(s.page(modified_source=None))
    with pytest.raises(ValidationError, match="review_due"):
        PageMeta.model_validate(s.page(review_due="2030-01-01"))


def test_effective_date_follows_the_precedence():
    with pytest.raises(ValidationError, match="effective"):
        PageMeta.model_validate(s.page(effective_date="2026-03-01", effective_source="schema_org"))
    no_review = s.page(
        date_reviewed=None,
        reviewed_source=None,
        effective_date="2026-03-01",
        effective_source="schema_org",
    )
    assert PageMeta.model_validate(no_review).effective_source == "schema_org"
    undated = {
        "url": "https://x.org/",
        "outcome": "blocked",
        "status": 403,
        "fetched_at": "2026-11-15T10:00:00Z",
    }
    assert PageMeta.model_validate(undated).effective_date is None


def test_modified_before_published_is_rejected():
    cands = [s.candidate("modified", "2020-01-01"), s.candidate("published", "2024-01-10")]
    with pytest.raises(ValidationError, match="before date_published"):
        PageMeta.model_validate(
            s.page(
                candidates=cands,
                date_modified="2020-01-01",
                date_reviewed=None,
                reviewed_source=None,
                review_due=None,
                effective_date="2020-01-01",
                effective_source="schema_org",
            )
        )
