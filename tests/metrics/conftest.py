"""A tiny hand-built study whose §6 figures can be worked out on paper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

QUESTIONS = [
    {
        "id": "t-001",
        "text": "Q one?",
        "intent": "alpha",
        "time_sensitive": True,
        "ts_reason": "services",
    },
    {"id": "t-002", "text": "Q two?", "intent": "alpha", "time_sensitive": False},
    {
        "id": "t-003",
        "text": "Q three?",
        "intent": "beta",
        "time_sensitive": True,
        "ts_reason": "prices",
    },
    {"id": "t-004", "text": "Q four?", "intent": "beta", "time_sensitive": False},
]
A, B = "claude-sonnet-5-5", "gpt-6.1-sol"
# (run, question, model) -> list of (url, publisher); None = refusal
CITES = {
    (1, "t-001", A): [("https://nhs.uk/a", "nhs.uk"), ("https://bbc.co.uk/a", "bbc.co.uk")],
    (1, "t-002", A): [],
    (1, "t-003", A): [("https://nhs.uk/b", "nhs.uk")],
    (1, "t-004", A): None,
    (1, "t-001", B): [("https://nhs.uk/a", "nhs.uk")],
    (1, "t-002", B): [
        ("https://x.com/a", "x.com"),
        ("https://x.com/b", "x.com"),
        ("https://nhs.uk/c", "nhs.uk"),
    ],
    (1, "t-003", B): [("https://bbc.co.uk/a", "bbc.co.uk")],
    (1, "t-004", B): [],
    (2, "t-001", A): [("https://nhs.uk/a", "nhs.uk")],
    (2, "t-002", A): [("https://bbc.co.uk/a", "bbc.co.uk")],
    (2, "t-003", A): [("https://nhs.uk/b", "nhs.uk")],
    (2, "t-004", A): [],
    (2, "t-001", B): [("https://nhs.uk/a", "nhs.uk")],
    (2, "t-002", B): [("https://x.com/a", "x.com")],
    (2, "t-003", B): [("https://bbc.co.uk/a", "bbc.co.uk")],
    (2, "t-004", B): [],
}
# answered 2026-11-20; nhs.uk/a dated 2026-01-01 (323 days), nhs.uk/b 2024-01-01 (stale),
# bbc.co.uk/a modified after the answer, x.com undated
PAGES = {
    "https://nhs.uk/a": ("2026-01-01", "2026-06-01"),
    "https://nhs.uk/b": ("2024-01-01", "2027-01-01"),
    "https://bbc.co.uk/a": ("2026-12-01", None),
    "https://nhs.uk/c": ("2025-11-01", None),
    "https://x.com/a": (None, None),
    "https://x.com/b": (None, None),
}


def write(base: Path) -> Path:
    data = base / "data"
    data.mkdir(parents=True)
    cfg = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "studies" / "uk-health" / "study.yaml").read_text(
            encoding="utf-8"
        )
    )
    cfg["intents"] = ["alpha", "beta"]
    (base / "study.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (base / "questions.jsonl").write_text(
        "".join(json.dumps(q) + "\n" for q in QUESTIONS), encoding="utf-8"
    )
    answers, cites = [], []
    for (run, qid, model), cs in CITES.items():
        answers.append(
            {
                "run": run,
                "question_id": qid,
                "model": model,
                "answered_at": "2026-11-20T10:00:00Z",
                "error": None,
                "refusal": cs is None,
                "search_errors": [],
                "over_length": False,
            }
        )
        for o, (url, pub) in enumerate(cs or [], 1):
            cites.append(
                {
                    "run": run,
                    "question_id": qid,
                    "model": model,
                    "url": url,
                    "publisher": pub,
                    "ordinal": o,
                }
            )
    pages = [
        {
            "url": u,
            "effective_date": e,
            "review_due": r,
            "outcome": "ok",
            "fetched_at": "2026-11-21T00:00:00Z",
        }
        for u, (e, r) in PAGES.items()
    ]
    for name, rows in (
        ("answers", answers),
        ("citations", cites),
        ("page_meta", pages),
        ("consulted", cites),
    ):
        (data / f"{name}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
    (data / "spend-ledger.jsonl").write_text(
        '{"spent_usd": 0.25}\n{"spent_usd": 0.5}\n', encoding="utf-8"
    )
    return base


@pytest.fixture
def tiny(tmp_path: Path) -> Path:
    return write(tmp_path / "tiny")
