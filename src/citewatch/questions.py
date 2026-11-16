"""The mechanical rules of a study's question rubric (QST-02).

`RUBRIC.md` holds the judgement rules (natural phrasing, one need per question, the
time-sensitive rule); this lint enforces the ones a machine can check: at most 30 words, no
domain names, no listed publisher or brand names. "NHS" is allowed where people ask about
getting care through it ("on the NHS", "NHS 111", "the NHS App"), never as a source request.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from citewatch.schemas import StudyConfig, StudyQuestion

MAX_WORDS = 30
_DOMAIN = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|uk|gov|io|info|co|nhs|scot|wales)\b", re.I
)
PUBLISHERS = (
    "bbc", "boots", "bupa", "superdrug", "patient.info", "webmd", "mayo clinic", "healthline",
    "medical news today", "nice", "gov.uk", "the guardian", "daily mail", "wikipedia",
    "cancer research", "macmillan", "british heart foundation", "diabetes uk", "mind",
    "versus arthritis", "nhs inform", "nhs choices", "public health england", "ukhsa",
)  # fmt: skip
_SOURCE_ASK = re.compile(
    r"\baccording to (the )?nhs\b|\bwhat (does|do) (the )?nhs (say|says|recommend|advise)\b"
    r"|\bnhs (says|recommends|advises)\b",
    re.I,
)


def question_problems(q: StudyQuestion) -> list[str]:
    problems = []
    words = len(q.text.split())
    if words > MAX_WORDS:
        problems.append(f"{q.id}: {words} words (at most {MAX_WORDS})")
    if _DOMAIN.search(q.text):
        problems.append(f"{q.id}: names a domain ({_DOMAIN.search(q.text).group(0)})")  # type: ignore[union-attr]
    low = f" {q.text.lower()} "
    for name in PUBLISHERS:
        if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", low):
            problems.append(f"{q.id}: names a publisher or brand ({name})")
    if _SOURCE_ASK.search(q.text):
        problems.append(f'{q.id}: asks for a source ("what the NHS says")')
    return problems


def lint_questions(
    qs: Sequence[StudyQuestion],
    cfg: StudyConfig,
    *,
    per_intent: int | None = None,
    min_ts: int | None = None,
) -> list[str]:
    """Every rubric rule a machine can check, for the whole set."""
    problems: list[str] = []
    ids = Counter(q.id for q in qs)
    problems += [f"{i}: duplicate id" for i, n in ids.items() if n > 1]
    for q in qs:
        if q.intent not in cfg.intents:
            problems.append(f"{q.id}: intent {q.intent!r} is not declared")
        problems += question_problems(q)
    if per_intent is not None:
        counts = Counter(q.intent for q in qs)
        problems += [
            f"intent {i}: {counts[i]} questions (want {per_intent})"
            for i in cfg.intents
            if counts[i] != per_intent
        ]
    if min_ts is not None:
        ts = Counter(q.intent for q in qs if q.time_sensitive)
        problems += [
            f"intent {i}: {ts[i]} time-sensitive (want at least {min_ts})"
            for i in cfg.intents
            if ts[i] < min_ts
        ]
    return problems
