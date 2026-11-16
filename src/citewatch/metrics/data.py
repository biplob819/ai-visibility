"""The study's data files as per-answer records for the metrics (Tech Spec §6).

An **answer** is a (run, question, model) record; a **valid answer** has no transport error
and no refusal. P(a) is the set of publishers among answer a's unique canonical URLs.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from citewatch.schemas import StudyConfig, StudyQuestion


@dataclass(frozen=True)
class Cite:
    url: str
    publisher: str
    group: str | None = None


@dataclass
class Answer:
    run: int
    qid: str
    model: str
    intent: str
    time_sensitive: bool
    answered_at: dt.datetime
    valid: bool
    refusal: bool
    error: bool
    search_errors: bool
    over_length: bool
    raw_citations: int = 0
    cites: list[Cite] = field(default_factory=list)  # unique canonical URLs, first-seen order
    consulted: list[Cite] = field(default_factory=list)

    @property
    def publishers(self) -> set[str]:
        return {c.publisher for c in self.cites}

    @property
    def consulted_publishers(self) -> set[str]:
        return {c.publisher for c in self.consulted}


@dataclass(frozen=True)
class Page:
    url: str
    effective_date: dt.date | None
    review_due: dt.date | None
    outcome: str


@dataclass
class StudyData:
    questions: list[StudyQuestion]
    answers: list[Answer]
    pages: dict[str, Page]
    spend_usd: float
    latest: dt.datetime | None

    @property
    def qids(self) -> list[str]:
        """The clusters the bootstrap resamples: questions with at least one answer in the
        chosen runs (all 100 in a study run; the 10 asked in a smoke run)."""
        return sorted({a.qid for a in self.answers})

    def runs(self) -> list[int]:
        return sorted({a.run for a in self.answers})

    def models(self) -> list[str]:
        return sorted({a.model for a in self.answers})


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _ts(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def _date(s: str | None) -> dt.date | None:
    return None if not s else dt.date.fromisoformat(s[:10])


def _ledger_run(run_id: str) -> int | None:
    tail = run_id.rsplit(":run-", 1)
    return int(tail[1]) if len(tail) == 2 and tail[1].isdigit() else None


def load(
    base: Path, cfg: StudyConfig, questions: list[StudyQuestion], runs: list[int] | None = None
) -> StudyData:
    data = base / "data"
    qmap = {q.id: q for q in questions}
    answers: dict[tuple[int, str, str], Answer] = {}
    latest: dt.datetime | None = None
    for r in _rows(data / "answers.jsonl"):
        if runs is not None and r["run"] not in runs:
            continue
        q = qmap.get(r["question_id"])
        if q is None or r["model"] not in cfg.models:
            continue  # a question or model no longer in the study is not measured
        at = _ts(r["answered_at"])
        latest = at if latest is None or at > latest else latest
        error = r.get("error") is not None
        answers[(r["run"], r["question_id"], r["model"])] = Answer(
            run=r["run"],
            qid=r["question_id"],
            model=r["model"],
            intent=q.intent,
            time_sensitive=q.time_sensitive,
            answered_at=at,
            valid=not error and not r["refusal"],
            refusal=bool(r["refusal"]),
            error=error,
            search_errors=bool(r.get("search_errors")),
            over_length=bool(r.get("over_length")),
        )
    for r in _rows(data / "citations.jsonl"):
        a = answers.get((r["run"], r["question_id"], r["model"]))
        if a is None:
            continue
        a.raw_citations += 1
        if all(c.url != r["url"] for c in a.cites):
            a.cites.append(Cite(r["url"], r["publisher"], r.get("publisher_group")))
    for r in _rows(data / "consulted.jsonl"):
        a = answers.get((r["run"], r["question_id"], r["model"]))
        if a is not None and all(c.url != r["url"] for c in a.consulted):
            a.consulted.append(Cite(r["url"], r["publisher"]))
    pages: dict[str, Page] = {}
    for r in _rows(data / "page_meta.jsonl"):
        pages[r["url"]] = Page(
            url=r["url"],
            effective_date=_date(r.get("effective_date")),
            review_due=_date(r.get("review_due")),
            outcome=r.get("outcome") or "not_fetched",
        )
        if r.get("fetched_at"):
            at = _ts(r["fetched_at"])
            latest = at if latest is None or at > latest else latest
    scored = {a.run for a in answers.values()}
    spend = math.fsum(  # the scored runs' paid calls only (v1 M4): `<study>:run-N`
        float(r.get("spent_usd", 0.0))
        for r in _rows(data / "spend-ledger.jsonl")
        if _ledger_run(r.get("run_id", "")) in scored
    )
    ordered = sorted(answers.values(), key=lambda a: (a.run, a.qid, a.model))
    return StudyData(list(questions), ordered, pages, round(spend, 6), latest)
