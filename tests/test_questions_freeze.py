"""QST-02 / QST-03: the question rubric's mechanical rules and the pre-registration freeze."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from citewatch.questions import lint_questions, question_problems
from citewatch.schemas import StudyQuestion, load_questions, load_study_config

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / "studies" / "uk-health"
# OWNER D-47: frozen 2026-11-16, before run 1. Never edit these to make a test pass.
QUESTIONS_SHA256 = "db169fec5d7dfb90a5f45a73990016d762b1fef3656900ee44adf3627547824e"
PREREG_SHA256 = "d8166467572f8e5451d4a00ec4996bfdc8456e1d5669531e7e807802f35733fd"


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
