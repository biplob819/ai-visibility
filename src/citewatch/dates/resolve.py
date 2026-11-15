"""Precedence and the chosen dates (Tech Spec §6.2, §7.3, DAT-03)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from citewatch.schemas import DateCandidate, PageMeta

from .rules import apply_rules

PRECEDENCE = {
    "reviewed": ("visible_text", "schema_org", "microdata"),
    "modified": (
        "schema_org",
        "microdata",
        "meta_tag",
        "visible_text",
        "sitemap",
        "page_age",
        "http_header",
    ),
    "published": (
        "schema_org",
        "microdata",
        "meta_tag",
        "visible_text",
        "sitemap",
        "page_age",
        "http_header",
    ),
    "review_due": ("visible_text",),
}


def choose(cands: list[DateCandidate], kind: str) -> DateCandidate | None:
    """The first source in precedence with a usable candidate; within it the latest value
    (the earliest for `published`)."""
    usable = [c for c in cands if c.kind == kind and c.rejected is None]
    for source in PRECEDENCE[kind]:
        here = [c for c in usable if c.source == source]
        if here:
            return (
                min(here, key=lambda c: c.value)
                if kind == "published"
                else max(here, key=lambda c: c.value)
            )
    return None


def _dedupe(cands: list[DateCandidate]) -> list[DateCandidate]:
    seen: set[tuple[str, dt.date, str]] = set()
    out = []
    for c in cands:
        k = (c.kind, c.value, c.source)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def resolve_dates(
    url: str,
    *,
    outcome: str,
    status: int | None,
    fetched_at: dt.datetime | None,
    final_url: str | None,
    candidates: list[DateCandidate],
) -> PageMeta:
    cands = apply_rules(_dedupe(candidates), fetched_at, lambda cs: choose(cs, "published"))
    picked: dict[str, Any] = {}
    for kind, field in (
        ("modified", "date_modified"),
        ("published", "date_published"),
        ("reviewed", "date_reviewed"),
    ):
        c = choose(cands, kind)
        picked[field] = None if c is None else c.value
        picked[f"{kind}_source"] = None if c is None else c.source
    due = choose(cands, "review_due")
    if picked["date_reviewed"] is not None:
        eff, src = picked["date_reviewed"], picked["reviewed_source"]
    elif picked["date_modified"] is not None:
        eff, src = picked["date_modified"], picked["modified_source"]
    elif picked["date_published"] is not None:
        eff, src = picked["date_published"], picked["published_source"]
    else:
        eff, src = None, None
    return PageMeta(
        url=url,
        fetched_at=fetched_at,
        outcome=outcome,  # type: ignore[arg-type]
        status=status,
        final_url=final_url,
        candidates=tuple(cands),
        review_due=None if due is None else due.value,
        effective_date=eff,
        effective_source=src,
        **picked,
    )
