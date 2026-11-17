"""`results/summary.json` (MET-08): every §6 metric with its interval, coverage, error counts
and spend. The same data always gives the same bytes: `generated_at` is the latest timestamp in
the data, not the clock."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from citewatch.runners.schedule import config_hash
from citewatch.schemas import SCHEMA_VERSION, StudyConfig, StudyQuestion, StudySummary

from . import compute
from .data import StudyData, load
from .stats import RESAMPLES, resample_matrix, wilson

COVERAGE_TARGET = 0.9  # FR9


def _sha(path: Path | None) -> str:
    return hashlib.sha256(path.read_bytes() if path and path.is_file() else b"").hexdigest()


def preregistration_for(study_dir: Path) -> Path | None:
    """The study's own `preregistration.md`, else the nearest `docs/preregistration.md` above."""
    own = study_dir / "preregistration.md"
    if own.is_file():
        return own
    for parent in [study_dir, *study_dir.resolve().parents]:
        p = parent / "docs" / "preregistration.md"
        if p.is_file():
            return p
    return None


def coverage(data: StudyData) -> tuple[int, int]:
    """Cited URLs with a resolved date or a logged reason (an outcome other than `ok`)."""
    urls = {c.url for a in data.answers for c in a.cites}
    k = 0
    for u in urls:
        page = data.pages.get(u)
        if page is not None and (page.effective_date is not None or page.outcome != "ok"):
            k += 1
    return k, len(urls)


def error_counts(data: StudyData, excluded: dict[str, int]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for m in data.models():
        xs = [a for a in data.answers if a.model == m]
        out[m] = {
            "answers": len(xs),
            "refusal": sum(a.refusal for a in xs),
            "transport": sum(a.error for a in xs),
            "search_error": sum(a.search_errors for a in xs),
            "over_length": sum(a.over_length for a in xs),
            "zero_citation": sum(a.valid and not a.cites for a in xs),
        }
    if excluded:
        out["overlap_excluded"] = dict(sorted(excluded.items()))
    undated: dict[str, int] = {}  # undated cited pages, by fetch outcome (pre-registration)
    for u in sorted({c.url for a in data.answers for c in a.cites}):
        page = data.pages.get(u)
        if page is None or page.effective_date is None:
            reason = "missing" if page is None else page.outcome
            undated[reason] = undated.get(reason, 0) + 1
    if undated:
        out["undated_pages"] = dict(sorted(undated.items()))
    no_due: dict[str, int] = {}  # cited NHS pages with no review date, by outcome (v2 L2)
    nhs_urls = {
        c.url for a in data.answers for c in a.cites if compute.NHS in (c.publisher, c.group)
    }
    for u in sorted(nhs_urls):
        page = data.pages.get(u)
        if page is None or page.review_due is None:
            reason = "missing" if page is None else page.outcome
            no_due[reason] = no_due.get(reason, 0) + 1
    if no_due:
        out["nhs_no_review_date"] = dict(sorted(no_due.items()))
    return out


def build_summary(
    base: Path,
    cfg: StudyConfig,
    questions: list[StudyQuestion],
    runs: list[int] | None = None,
    resamples: int = RESAMPLES,
) -> StudySummary:
    data = load(base, cfg, questions, runs)
    if not data.answers:
        raise ValueError("no answers to score for the chosen runs")
    w = resample_matrix(len(data.qids), cfg.seeds["bootstrap"], resamples)
    ctx = compute.Ctx(data, w, cfg.stale_days)
    overlap, excluded = compute.overlap(ctx)
    k, n = coverage(data)
    accuracy_rows, hand_counts = _date_accuracy(base)
    errors = error_counts(data, excluded)
    if hand_counts:
        errors["hand_dates"] = hand_counts
    support = _support(base, cfg)
    methods = {}
    if accuracy_rows:
        methods["date_accuracy"] = DATE_CHECK_METHOD
    if any(r.judge == "hand" for r in support):
        methods["support_hand"] = SUPPORT_HAND_METHOD
    return StudySummary(
        schema_version=SCHEMA_VERSION,
        runs=tuple(data.runs()),
        config_hash=config_hash(cfg),
        questions_sha256=_sha(base / cfg.questions_path),
        preregistration_sha256=_sha(preregistration_for(base)),
        share=tuple(compute.shares(ctx)),
        citations=tuple(compute.citations(ctx)),
        concentration=tuple(compute.concentration(ctx)),
        freshness=tuple(compute.freshness(ctx)),
        stale=tuple(compute.stale(ctx)),
        overlap=tuple(overlap),
        stability=tuple(compute.stability(ctx)),
        comparisons=tuple(compute.comparisons(ctx)),
        nhs_overdue=tuple(compute.overdue(ctx)),
        coverage=wilson(k, n),
        date_accuracy=tuple(accuracy_rows),
        support=tuple(support),
        check_methods=methods,
        error_counts=errors,
        spend_usd=data.spend_usd,
        generated_at=data.latest or dt.datetime(1970, 1, 1, tzinfo=dt.UTC),
    )


def _support(base: Path, cfg: StudyConfig) -> list:
    """SupportRows once the judges have run (M3.2); hand labels join when imported."""
    from citewatch.schemas import SupportVerdict
    from citewatch.support.report import load_hand_labels, support_rows

    path = base / "data" / "support_verdicts.jsonl"
    if not path.is_file():
        return []
    verdicts = [
        SupportVerdict.model_validate_json(x)
        for x in path.read_text(encoding="utf-8").splitlines()
        if x
    ]
    return support_rows(verdicts, load_hand_labels(base), cfg.seeds["support_sample"])


DATE_CHECK_METHOD = "agent-checked, owner-approved (OWNER D-63)"
SUPPORT_HAND_METHOD = "owner-labelled (OWNER D-62)"


def _hand_rows(base: Path) -> list[dict[str, Any]]:
    from citewatch.handcheck import LABELS_FILE

    path = base / "data" / LABELS_FILE
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _date_accuracy(base: Path) -> tuple[list, dict[str, int]]:
    """AccuracyRows and counts for the held-out date check (M3.3). Rows made against an older
    resolver are never scored; with too few current rows nothing is published (D-6)."""
    from citewatch.handcheck import (
        SAMPLE_FILE,
        accuracy,
        current_labels,
        labels_meta,
        publish_problems,
    )
    from citewatch.schemas import HandDateLabel

    data = base / "data"
    rows = _hand_rows(base)
    if not rows or not (data / SAMPLE_FILE).is_file():
        return [], {}
    sample = [
        json.loads(x) for x in (data / SAMPLE_FILE).read_text(encoding="utf-8").splitlines() if x
    ]
    sample_urls = {s["url"] for s in sample}
    current = [r for r in current_labels(rows) if r.get("url") in sample_urls]
    counts = {"labels": len(rows), "stale_labels": len(rows) - len(current_labels(rows))}
    if publish_problems(labels_meta(rows, sample_urls)):
        counts["blocked"] = 1
        return [], counts
    labels = {}
    for row in current:
        label = HandDateLabel.model_validate(
            {k: v for k, v in row.items() if k in HandDateLabel.model_fields}
        )
        labels[label.url] = label
    effective = {}
    for x in (data / "page_meta.jsonl").read_text(encoding="utf-8").splitlines():
        if x.strip():
            m = json.loads(x)
            effective[m["url"]] = (
                dt.date.fromisoformat(m["effective_date"]) if m.get("effective_date") else None
            )
    unreadable = {r["url"] for r in current if r.get("checker_loaded") is False}
    dated = [s for s in sample if s["role"] == "dated" and s["url"] in labels]
    counts["checker_could_not_load"] = len(unreadable)
    counts["unjudgeable"] = sum(  # dated by the parser; the checker loaded it and saw no date
        labels[s["url"]].not_determinable and s["url"] not in unreadable for s in dated
    )
    return accuracy(sample, labels, effective, unreadable), counts


def write_summary(base: Path, summary: StudySummary) -> Path:
    path = base / "results" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(summary.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path
