"""Regression tests for the N1.1 verifier's findings (RUN-STATE.md, pass 1)."""

import copy
import json
import pickle

import pytest
import yaml
from pydantic import ValidationError

from citewatch.schemas import (
    AnswerRecord,
    Citation,
    ConfigError,
    ConsultedSource,
    DomainCard,
    FreshnessRow,
    HandDateLabel,
    PageMeta,
    StudyConfig,
    StudySummary,
    SupportVerdict,
    count_words,
    load_questions,
    load_study_config,
)

from . import samples as s


def _cfg_file(tmp_path, **over):
    p = tmp_path / "study.yaml"
    p.write_text(yaml.safe_dump(s.config(**over)), encoding="utf-8")
    return p


# ---- disproved criteria ----


@pytest.mark.parametrize("url", ["HTTPS://www.nhs.uk/x", "Http://www.nhs.uk/x"])
def test_upper_case_scheme_is_not_canonical(url):
    with pytest.raises(ValidationError, match="lower case"):
        Citation.model_validate(s.citation(url=url))
    with pytest.raises(ValidationError, match="lower case"):
        ConsultedSource.model_validate(s.consulted(url=url))


@pytest.mark.parametrize(("code", "hint"), [("UK", "use 'GB'"), ("ZZ", ""), ("XX", "")])
def test_country_must_be_an_assigned_iso_code(tmp_path, code, hint):
    p = _cfg_file(tmp_path, user_location={"type": "approximate", "country": code})
    with pytest.raises(ConfigError, match="ISO 3166-1") as exc:
        load_study_config(p)
    assert hint in str(exc.value)


@pytest.mark.parametrize(
    "agent",
    [
        "citewatch/0.1 (+https://)",
        "citewatch/0.1 (+https://x)",
        "Mozilla/5.0 (Windows NT 10.0) Chrome/120 https://x.io",
        "citewatch/0.1 (+https://github.com/me/x)\r\nX-Injected: 1",
        "citewatch/0.1 (contact: me)",
    ],
)
def test_user_agent_names_the_tool_and_a_real_contact(tmp_path, agent):
    with pytest.raises(ConfigError, match="user_agent"):
        load_study_config(_cfg_file(tmp_path, user_agent=agent))


def test_user_agent_accepts_a_url_or_an_email(tmp_path):
    for agent in (
        "citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)",
        "citewatch/0.1.0 (study@examplehealth.org)",
    ):
        assert load_study_config(_cfg_file(tmp_path, user_agent=agent)).user_agent == agent


# ---- medium findings ----


def test_frozen_records_can_be_pickled_and_deep_copied():
    for obj in (
        StudyConfig.model_validate(s.config()),
        DomainCard.model_validate(s.card()),
        StudySummary.model_validate(s.summary()),
    ):
        assert pickle.loads(pickle.dumps(obj)) == obj
        assert copy.deepcopy(obj) == obj
        assert obj.model_copy(deep=True) == obj
    card = pickle.loads(pickle.dumps(DomainCard.model_validate(s.card())))
    with pytest.raises(TypeError):
        card.share_by_model["x"] = card.share_by_model["claude-sonnet-5-5"]  # type: ignore[index]


def test_each_study_declares_its_own_time_sensitive_reasons(tmp_path):
    q = s.question(id="v-001", intent="symptoms", ts_reason="regulation")
    qfile = tmp_path / "q.jsonl"
    qfile.write_text(json.dumps(q) + "\n", encoding="utf-8")
    open_cfg = StudyConfig.model_validate(s.config())
    assert load_questions(qfile, open_cfg)[0].ts_reason == "regulation"
    strict = StudyConfig.model_validate(s.config(ts_reasons=["prices", "guidance"]))
    with pytest.raises(ConfigError, match="not in the study's rubric"):
        load_questions(qfile, strict)


# ---- low findings fixed cheaply ----


def test_transport_errors_need_no_raw_key_and_others_need_one():
    ok = AnswerRecord.model_validate(
        s.answer(raw_key=None, error="transport", answer_text="", word_count=0, searches=0)
    )
    assert ok.raw_key is None
    with pytest.raises(ValidationError, match="raw_key"):
        AnswerRecord.model_validate(s.answer(raw_key=None))
    with pytest.raises(ValidationError, match="raw_key"):
        AnswerRecord.model_validate(s.answer(error="transport"))


def test_timestamps_must_be_utc():
    with pytest.raises(ValidationError, match="UTC"):
        AnswerRecord.model_validate(s.answer(answered_at="2026-11-15T15:30:00+05:30"))
    assert AnswerRecord.model_validate(s.answer(answered_at="2026-11-15T10:00:00+00:00"))


@pytest.mark.parametrize("over", [{"cost_usd": True}, {"cost_usd": "0.07"}])
def test_money_rejects_bools_and_strings(over):
    with pytest.raises(ValidationError):
        AnswerRecord.model_validate(s.answer(**over))


@pytest.mark.parametrize(
    "quote",
    ["The U.K. guidance is reviewed every year.", "Walk daily, e.g. brisk walking, for health."],
)
def test_abbreviations_are_one_sentence(quote):
    assert SupportVerdict.model_validate(s.verdict(quote=quote)).quote == quote


@pytest.mark.parametrize(
    "ref", ["1:v-017:claude-sonnet-5-5:0", "1:v-017:llama-3:1", "3:v-017:gpt-6.1-sol:1"]
)
def test_citation_ref_shape(ref):
    with pytest.raises(ValidationError):
        SupportVerdict.model_validate(s.verdict(citation_ref=ref))


def test_publisher_must_be_the_host_or_its_parent_and_no_user_info():
    with pytest.raises(ValidationError, match="publisher"):
        Citation.model_validate(s.citation(publisher="bbc.co.uk"))
    trust = s.citation(
        url="https://guysandstthomas.nhs.uk/a",
        host="guysandstthomas.nhs.uk",
        publisher="guysandstthomas.nhs.uk",
        publisher_group="nhs.uk",
    )
    assert Citation.model_validate(trust)
    with pytest.raises(ValidationError, match="user info"):
        Citation.model_validate(s.citation(url="https://u:p@www.nhs.uk/x"))


def test_hand_label_dates_in_order():
    with pytest.raises(ValidationError, match="before"):
        HandDateLabel.model_validate(s.hand_label(true_published="2027-01-01"))


def test_questions_file_with_a_bom_loads(tmp_path):
    q = s.question(id="v-001", intent="symptoms", time_sensitive=False, ts_reason=None)
    p = tmp_path / "q.jsonl"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(q).encode() + b"\n")
    assert load_questions(p, StudyConfig.model_validate(s.config()))[0].id == "v-001"


# ---- surviving mutants: pin each rule ----


def test_page_rules_each_pinned():
    with pytest.raises(ValidationError, match="fetched_at and status"):
        PageMeta.model_validate(s.page(status=None))
    with pytest.raises(ValidationError, match="effective"):
        PageMeta.model_validate(s.page(effective_source="schema_org"))
    # a candidate of the wrong kind does not back a chosen date
    cands = [s.candidate("published", "2026-03-01"), s.candidate("published", "2024-01-10")]
    with pytest.raises(ValidationError, match="not backed"):
        PageMeta.model_validate(
            s.page(
                candidates=cands,
                date_reviewed=None,
                reviewed_source=None,
                review_due=None,
                effective_date="2026-03-01",
                effective_source="schema_org",
            )
        )
    rejected_due = s.page()
    rejected_due["candidates"] = [
        c if c["kind"] != "review_due" else {**c, "rejected": "x"}
        for c in rejected_due["candidates"]
    ]
    with pytest.raises(ValidationError, match="review_due"):
        PageMeta.model_validate(rejected_due)


@pytest.mark.parametrize("url", ["https:///x", "https://www.nhs.uk/x#", "https://WWW.nhs.uk/x"])
def test_consulted_urls_are_canonical(url):
    with pytest.raises(ValidationError):
        ConsultedSource.model_validate(s.consulted(url=url))


@pytest.mark.parametrize(
    "over",
    [
        {"max_searches": 0},
        {"word_limit": 0},
        {"stale_days": 0},
        {"models": ["gpt-6.1-sol", "gpt-6.1-sol"]},
        {"max_cost_usd": -1},
    ],
)
def test_config_bounds(tmp_path, over):
    with pytest.raises(ConfigError):
        load_study_config(_cfg_file(tmp_path, **over))


def test_empty_questions_file(tmp_path):
    p = tmp_path / "q.jsonl"
    p.write_text("\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no questions"):
        load_questions(p, StudyConfig.model_validate(s.config()))


def test_freshness_row_rules():
    base = {
        "publisher": "nhs.uk",
        "dated_pages": 3,
        "median_lag_days": 10.0,
        "iqr_days": [5.0, 20.0],
        "modified_after_answer": 0,
    }
    assert FreshnessRow.model_validate(base)
    with pytest.raises(ValidationError):
        FreshnessRow.model_validate({**base, "median_lag_days": None})
    with pytest.raises(ValidationError):
        FreshnessRow.model_validate({**base, "iqr_days": [20.0, 5.0]})


@pytest.mark.parametrize(
    "over",
    [
        {"error": "timeout"},
        {"run": -1},
        {"model": "Claude-Sonnet"},
    ],
)
def test_answer_literals_and_patterns(over):
    with pytest.raises(ValidationError):
        AnswerRecord.model_validate(s.answer(**over))


def test_citation_ordinal_is_strict():
    with pytest.raises(ValidationError):
        Citation.model_validate(s.citation(ordinal="1"))


@pytest.mark.parametrize(
    "over",
    [{"questions_sha256": "ab" * 31}, {"questions_sha256": "AB" * 32}, {"schema_version": "1"}],
)
def test_summary_hash_and_version_patterns(over):
    with pytest.raises(ValidationError):
        StudySummary.model_validate(s.summary(**over))


def test_count_words_splits_on_any_whitespace():
    assert count_words("one\ttwo") == 2


# ---- N1.1 verifier pass 2 ----


@pytest.mark.parametrize(
    "url", ["https://www.nh\ns.uk/x", "https://www.nhs.uk/x\n", "https://www.nhs.uk/a b"]
)
def test_canonical_urls_have_no_whitespace(url):
    with pytest.raises(ValidationError, match="whitespace"):
        Citation.model_validate(s.citation(url=url))


def test_page_status_is_strict_and_consulted_publisher_matches():
    with pytest.raises(ValidationError):
        PageMeta.model_validate(s.page(status="200"))
    with pytest.raises(ValidationError, match="publisher"):
        ConsultedSource.model_validate(s.consulted(publisher="bbc.co.uk"))
    with pytest.raises(ValidationError, match="publisher"):
        ConsultedSource.model_validate(s.consulted(publisher="hs.uk"))  # dot boundary


def test_user_agent_is_printable_ascii(tmp_path):
    with pytest.raises(ConfigError, match="ASCII"):
        load_study_config(_cfg_file(tmp_path, user_agent="citewatch/0.1 (josé@example.org)"))


@pytest.mark.parametrize(
    ("model", "data"),
    [
        ("interval", {"point": "0.2", "lo": 0.1, "hi": 0.3, "n": 1}),
        ("interval", {"point": True, "lo": 0.0, "hi": 1.0, "n": 1}),
    ],
)
def test_finite_floats_are_strict(model, data):
    from citewatch.schemas import Interval

    with pytest.raises(ValidationError):
        Interval.model_validate(data)


@pytest.mark.parametrize("model", ["CLAUDE-sonnet", "claude sonnet", "gpt-6.1 sol"])
def test_model_id_pattern(model):
    with pytest.raises(ValidationError):
        AnswerRecord.model_validate(s.answer(model=model))


def test_verdict_literals():
    with pytest.raises(ValidationError):
        SupportVerdict.model_validate(s.verdict(verdict="maybe"))
    with pytest.raises(ValidationError):
        SupportVerdict.model_validate(s.verdict(hand_label="partly"))


def test_page_vocabularies_match_the_tech_spec():
    import re
    import typing

    from citewatch.schemas import pages
    from harness_lib import ROOT

    spec = (ROOT / "AI Visibility Tech Spec.md").read_text(encoding="utf-8")
    sec = spec[
        spec.index("class DateCandidate(BaseModel):") : spec.index("class Interval(BaseModel):")
    ]

    def literal(name: str) -> set[str]:
        m = re.search(rf"{name}: Literal\[(.*?)\]", sec, re.S)
        assert m, name
        return set(re.findall(r'"(\w+)"', m.group(1)))

    assert set(typing.get_args(pages.DateKind)) == literal("kind")
    assert set(typing.get_args(pages.DateSource)) == literal("source")
    assert set(typing.get_args(pages.Outcome)) == literal("outcome")


def test_summary_money_and_counts_are_non_negative():
    with pytest.raises(ValidationError):
        StudySummary.model_validate(s.summary(spend_usd=-1))
    with pytest.raises(ValidationError):
        StudySummary.model_validate(s.summary(preregistration_sha256="ab" * 31))
    with pytest.raises(ValidationError):
        StudySummary.model_validate(s.summary(error_counts={"m": {"refusal": -1}}))


def test_frozen_dict_blocks_update_and_merge():
    card = DomainCard.model_validate(s.card())
    with pytest.raises(TypeError):
        card.share_by_model.update({})  # type: ignore[attr-defined]
    m = card.share_by_model
    with pytest.raises(TypeError):
        m |= {}  # type: ignore[operator]


def test_fixture_list_covers_every_top_level_spec_record():
    from tests.schemas.test_format import TOP_LEVEL

    nested = {
        "DateCandidate",
        "Interval",
        "ShareRow",
        "ConcentrationRow",
        "FreshnessRow",
        "StaleRow",
        "OverlapRow",
        "StabilityRow",
        "AccuracyRow",
        "SupportRow",
        "CitationsRow",
        "OverdueRow",
        "ComparisonRow",
    }
    from tests.schemas.test_format import spec_schema_names

    assert spec_schema_names() - nested == set(TOP_LEVEL.values())
