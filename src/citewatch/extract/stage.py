"""The extract stage: answers, citations and consulted sources rebuilt from the raw store.

Pure: it reads only stored envelopes, so a fixed extractor reruns over every answer for free
(D-2). Writes `<study>/data/answers.jsonl`, `citations.jsonl` and `consulted.jsonl`.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from citewatch.runners import anthropic_runner, openai_runner
from citewatch.schemas import (
    AnswerRecord,
    Citation,
    ConsultedSource,
    StudyConfig,
    count_words,
    provider_of,
)
from citewatch.store import RawStore

from .extractors import Extracted, canonical_or_none, extract_claude, extract_openai, host_of
from .urls import publisher_of

EXTRACT_VERSION = "extract-1"


@dataclass
class ExtractResult:
    answers: list[AnswerRecord] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    consulted: list[ConsultedSource] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    skipped_urls: Counter[str] = field(default_factory=Counter)


def _refusal(model: str, responses: list[dict[str, Any]], request: dict[str, Any]) -> bool:
    if provider_of(model) == "anthropic":
        return anthropic_runner.parse(model, responses, request).refusal
    return openai_runner.parse(model, responses[-1], request).refusal


def extract_envelope(
    key: str, env: dict[str, Any], cfg: StudyConfig
) -> tuple[AnswerRecord, list[Citation], list[ConsultedSource], list[str]]:
    model, responses = env["model"], env["responses"]
    ex: Extracted = (
        extract_claude(responses)
        if provider_of(model) == "anthropic"
        else extract_openai(responses)
    )
    usage = env.get("usage") or {}
    snapshot = (responses[-1].get("model") if responses else None) or model
    searches = int(usage.get("searches") or 0)
    errors: list[str] = []
    if provider_of(model) == "anthropic":
        errors = anthropic_runner.parse(model, responses, env.get("request") or {}).search_errors
    words = count_words(ex.answer_text)
    rec = AnswerRecord(
        run=env["run"],
        question_id=env["question_id"],
        model=model,
        model_snapshot=snapshot,
        raw_key=key,
        answer_text=ex.answer_text,
        word_count=words,
        over_length=words > cfg.word_limit,
        searches=searches,
        search_errors=tuple(errors),
        refusal=_refusal(model, responses, env.get("request") or {}),
        tokens_in=int(usage.get("tokens_in") or 0),
        tokens_out=int(usage.get("tokens_out") or 0),
        cost_usd=float(env.get("cost_usd") or 0.0),
        answered_at=env["answered_at"],
        prompt_hash=env["prompt_hash"],
        config_hash=env["answer_config_hash"],
    )
    skipped: list[str] = []
    cites: list[Citation] = []
    cited_canon: set[str] = set()
    for n, c in enumerate(ex.citations, start=1):
        url = canonical_or_none(c.url_raw)
        if url is None:
            skipped.append(c.url_raw)
            continue
        pub, group = publisher_of(url)
        cites.append(
            Citation(
                run=env["run"],
                question_id=env["question_id"],
                model=model,
                url_raw=c.url_raw,
                url=url,
                host=host_of(url),
                publisher=pub,
                publisher_group=group,
                title=c.title,
                quoted_span=c.quoted_span,
                answer_span=c.answer_span,
                ordinal=n,
            )
        )
        cited_canon.add(url)
    consulted: dict[str, ConsultedSource] = {}
    for raw, age in ex.consulted.items():
        url = canonical_or_none(raw)
        if url is None or url in consulted:
            continue
        consulted[url] = ConsultedSource(
            run=env["run"],
            question_id=env["question_id"],
            model=model,
            url=url,
            publisher=publisher_of(url)[0],
            page_age=age,
            cited=url in cited_canon,
        )
    return rec, cites, list(consulted.values()), skipped


def unique_cited_urls(citations: list[Citation]) -> dict[tuple[int, str, str], list[str]]:
    """Per answer (run, question, model), its unique canonical URLs in first-cited order;
    the raw count is the number of citation rows (CIT-06)."""
    out: dict[tuple[int, str, str], list[str]] = {}
    for c in citations:
        urls = out.setdefault((c.run, c.question_id, c.model), [])
        if c.url not in urls:
            urls.append(c.url)
    return out


def run_extract(base: Path, cfg: StudyConfig) -> ExtractResult:
    store = RawStore(base)
    res = ExtractResult()
    for key in sorted(store.keys("ask")):
        env = store.get("ask", key)
        try:
            rec, cites, cons, skipped = extract_envelope(key, env, cfg)
        except Exception as exc:  # one odd envelope never stops the stage; it is reported
            res.problems.append(f"{key[:12]}: {type(exc).__name__}: {exc}"[:300])
            continue
        res.answers.append(rec)
        res.citations.extend(cites)
        res.consulted.extend(cons)
        res.skipped_urls.update(skipped)
    order = lambda r: (r.run, r.question_id, r.model)  # noqa: E731
    res.answers.sort(key=order)
    res.citations.sort(key=lambda c: (c.run, c.question_id, c.model, c.ordinal))
    res.consulted.sort(key=lambda c: (c.run, c.question_id, c.model, c.url))
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("answers.jsonl", res.answers),
        ("citations.jsonl", res.citations),
        ("consulted.jsonl", res.consulted),
    ):
        tmp = data / (name + ".tmp")
        tmp.write_text(
            "".join(
                json.dumps(r.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
                for r in rows
            ),
            encoding="utf-8",
            newline="\n",
        )
        tmp.replace(data / name)
    return res
