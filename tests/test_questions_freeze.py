"""QST-02 / QST-03: the question rubric's mechanical rules and the pre-registration freeze."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from citewatch.questions import lint_questions, question_problems
from citewatch.schemas import StudyQuestion, load_questions, load_study_config

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / "studies" / "uk-health"
# OWNER D-47, re-frozen under D-51 before run 1. Never edit these to make a test pass.
QUESTIONS_SHA256 = "aaa3a348ab5844e2ad1fac47e0b68a4b53fb08e1354a0f303cc3d60186bba071"
PREREG_SHA256 = "9e227483cc387386c0a2b7ca36161c24f77cd59eaee2eb173978c4a183f60cbb"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_the_question_set_is_frozen():
    assert sha(STUDY / "questions.jsonl") == QUESTIONS_SHA256


def test_the_preregistration_is_frozen():
    assert sha(ROOT / "docs" / "preregistration.md") == PREREG_SHA256


def test_the_hashes_are_recorded_in_decisions():
    d = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    assert QUESTIONS_SHA256[:16] in d and PREREG_SHA256[:16] in d


def test_the_preregistration_holds_section_6_verbatim():
    spec = (ROOT / "AI Visibility Tech Spec.md").read_text(encoding="utf-8")
    s = spec.index("## 6. Metric definitions")
    sec6 = spec[s : spec.index("\n---", s)].strip()
    pre = (ROOT / "docs" / "preregistration.md").read_text(encoding="utf-8")
    assert sec6 in pre and "## Seeds" in pre and "## Exclusions" in pre


def test_the_frozen_set_meets_the_rubric():
    cfg = load_study_config(STUDY / "study.yaml")
    qs = load_questions(STUDY / "questions.jsonl", cfg)
    assert len(qs) == 100
    assert lint_questions(qs, cfg, per_intent=20, min_ts=8) == []
    assert all(q.ts_reason in (cfg.ts_reasons or ()) for q in qs if q.time_sensitive)


def q(text: str, **kw) -> StudyQuestion:
    return StudyQuestion(
        id=kw.get("id", "v-001"), text=text, intent="symptoms", time_sensitive=False
    )


@pytest.mark.parametrize(
    "text",
    [
        " ".join(["word"] * 31),
        "Is the advice on nhs.uk about flu still right?",
        "What does Healthline say about sore muscles?",
        "According to the NHS, how much water should I drink?",
        "What does the NHS recommend for back pain?",
        "Is Boots cheaper for hay fever tablets?",
    ],
)
def test_the_lint_rejects_each_mechanical_breach(text):
    assert question_problems(q(text))


@pytest.mark.parametrize(
    "text",
    [
        "What does NHS 111 do?",
        "Can I get physio on the NHS?",
        "How do I book a GP appointment on the NHS App?",
    ],
)
def test_the_lint_allows_asking_about_nhs_services(text):
    assert question_problems(q(text)) == []


def test_the_lint_rejects_duplicates_undeclared_intents_and_short_sets():
    cfg = load_study_config(STUDY / "study.yaml")
    a = StudyQuestion(
        id="v-001", text="Why do my legs ache?", intent="symptoms", time_sensitive=False
    )
    b = a.model_copy(update={"intent": "astrology"})
    probs = lint_questions([a, b], cfg, per_intent=20, min_ts=8)
    assert any("duplicate id" in p for p in probs)
    assert any("not declared" in p for p in probs)
    assert any("want 20" in p for p in probs) and any("at least 8" in p for p in probs)


def test_the_study_settings_and_rubric_match_the_preregistration():
    """v1 L3: the settings block and rubric hash in the pre-registration match the live files."""
    pre = (ROOT / "docs" / "preregistration.md").read_text(encoding="utf-8")
    assert (STUDY / "study.yaml").read_text(encoding="utf-8").strip() in pre
    assert sha(STUDY / "RUBRIC.md") in pre
    assert QUESTIONS_SHA256 in pre and "alpha of 0.05" in pre


@pytest.mark.parametrize(
    "text",
    [
        "Is it nice to swim in winter?",
        "Is meditation good for the mind?",
        "Is a mind-body class good?",
    ],
)
def test_everyday_words_are_not_brands(text):
    """v1 L4: NICE and Mind are matched only as written."""
    assert question_problems(q(text)) == []


@pytest.mark.parametrize(
    "text", ["What does NICE advise on sleep?", "Does Mind have advice on anxiety?"]
)
def test_the_brands_still_count(text):
    assert question_problems(q(text))


def test_the_rubric_states_its_rules_with_examples():
    """QST-01: the phrasing rules and the time-sensitive rule, each with examples."""
    r = (STUDY / "RUBRIC.md").read_text(encoding="utf-8").lower()
    for clause in ("services", "eligibility", "waiting", "prices", "guidance", "30 words"):
        assert clause in r
    assert "ibuprofen" in r and "12 months" in r


def test_every_ts_reason_is_a_rubric_clause_and_reason_iff_flagged():
    cfg = load_study_config(STUDY / "study.yaml")
    for q in load_questions(STUDY / "questions.jsonl", cfg):
        assert (q.ts_reason is not None) == q.time_sensitive
        assert q.ts_reason is None or q.ts_reason in (cfg.ts_reasons or ())


def test_the_data_card_marks_unbuilt_work_as_planned():
    """QST-04: present tense only for what is built."""
    card = (ROOT / "DATA_CARD.md").read_text(encoding="utf-8")
    for part in (
        "## What is collected",
        "## What is discarded",
        "## Politeness",
        "## Quoted spans",
        "## Limits",
    ):
        assert part in card
    assert card.count("Planned") >= 2 and "M3.2" in card and "M3.3" in card
