"""Plausibility rules (Tech Spec §7.3, DAT-02). A rejected candidate stays, with the rule."""

from __future__ import annotations

import datetime as dt

from citewatch.schemas import DateCandidate

EARLIEST = dt.date(1995, 1, 1)
MODIFIED_STAMP_SOURCES = frozenset({"schema_org", "meta_tag"})


def apply_rules(cands: list[DateCandidate], fetched_at: dt.datetime | None) -> list[DateCandidate]:
    out = list(cands)

    def reject(i: int, rule: str) -> None:
        if out[i].rejected is None:
            out[i] = out[i].model_copy(update={"rejected": rule})

    fetched = None if fetched_at is None else fetched_at.astimezone(dt.UTC).date()
    for i, c in enumerate(out):
        future = fetched is not None and c.value > fetched + dt.timedelta(days=1)
        if c.value < EARLIEST or (future and c.kind != "review_due"):  # a due date is ahead
            reject(i, "out_of_range")
    if fetched is not None:
        for i, c in enumerate(out):
            near = abs((c.value - fetched).days) <= 1
            if c.source == "http_header" and near:
                reject(i, "dynamic_header")
            elif c.kind == "modified" and c.source in MODIFIED_STAMP_SOURCES and near:
                others = [
                    o
                    for j, o in enumerate(out)
                    if j != i
                    and o.source != c.source
                    and o.rejected is None
                    and abs((o.value - c.value).days) <= 7
                ]
                if not others:
                    reject(i, "cms_stamp")
    published = [c.value for c in out if c.kind == "published" and c.rejected is None]
    if published:
        first = min(published)
        for i, c in enumerate(out):
            if c.kind == "modified" and c.value < first:
                reject(i, "modified_before_published")
    return out
