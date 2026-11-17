"""Results format v1: fixtures round-trip byte for byte, and every Tech Spec §4 schema is
exported, checked against the spec itself rather than the package's own list (EvalKit L-10)."""

import re

import pytest

import citewatch.schemas as schemas
from harness_lib import ROOT

FIXTURES = ROOT / "tests" / "fixtures" / "v1"
TOP_LEVEL = {
    "study_question": "StudyQuestion",
    "answer_record": "AnswerRecord",
    "citation": "Citation",
    "consulted_source": "ConsultedSource",
    "page_meta": "PageMeta",
    "study_summary": "StudySummary",
    "domain_card": "DomainCard",
    "improvement": "Improvement",
    "support_verdict": "SupportVerdict",
    "hand_date_label": "HandDateLabel",
    "study_config": "StudyConfig",
}


def spec_schema_names() -> set[str]:
    spec = (ROOT / "AI Visibility Tech Spec.md").read_text(encoding="utf-8")
    section = spec[spec.index("## 4. Schemas") : spec.index("## 5. Interfaces")]
    return set(re.findall(r"^class (\w+)\(BaseModel\)", section, re.M))


@pytest.mark.contract
def test_every_tech_spec_schema_is_exported():
    names = spec_schema_names()
    assert len(names) >= 20  # the spec section really was parsed
    missing = sorted(n for n in names if not hasattr(schemas, n))
    assert missing == []


@pytest.mark.contract
@pytest.mark.parametrize(("stem", "cls"), sorted(TOP_LEVEL.items()))
def test_fixture_round_trips_byte_for_byte(stem, cls):
    model = getattr(schemas, cls)
    text = (FIXTURES / f"{stem}.json").read_text(encoding="utf-8")
    obj = model.model_validate_json(text)
    assert obj.model_dump_json(indent=2) + "\n" == text
    assert model.model_validate_json(obj.model_dump_json()) == obj


@pytest.mark.contract
def test_one_fixture_per_top_level_schema():
    assert sorted(p.stem for p in FIXTURES.glob("*.json")) == sorted(TOP_LEVEL)


@pytest.mark.contract
def test_unknown_fields_are_rejected_everywhere():
    from pydantic import ValidationError

    for stem, cls in TOP_LEVEL.items():
        model = getattr(schemas, cls)
        data = model.model_validate_json((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))
        dumped = {**data.model_dump(mode="json"), "unexpected": 1}
        with pytest.raises(ValidationError):
            model.model_validate(dumped)
