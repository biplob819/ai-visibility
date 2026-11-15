"""Plausibility rules (Tech Spec §7.3, DAT-02, D-45). A rejected candidate stays, with the rule.

Applied in passes so the result never depends on the order of the candidate list (A2.3 v1
H2): first the rules about one candidate alone (`out_of_range`, `dynamic_header`), then the
CMS-stamp rule against the survivors, then `modified_before_published` against the published
date precedence will actually choose (v1 H1), so the chosen dates are always consistent.

Dates are calendar days, so "within 24 hours of the fetch" means the fetch day or the day
either side of it (D-45).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from citewatch.schemas import DateCandidate

EARLIEST = dt.date(1995, 1, 1)
NEAR_DAYS = 1  # "within 24 hours": the fetch day or the day either side
CORROBORATE_DAYS = 7
# every copy of a CMS field, and sitemaps (often generated per request) (v2 H1, L1)
STAMP_SOURCES = frozenset({"schema_org", "meta_tag", "microdata", "sitemap"})
# a fresh CMS stamp is believed only when a source independent of the CMS agrees: its own
# JSON-LD, meta and microdata mirrors, generated sitemaps and future review dates do not count
INDEPENDENT_SOURCES = frozenset({"visible_text", "page_age"})


def apply_rules(
    cands: list[DateCandidate],
    fetched_at: dt.datetime | None,
    choose_published: Callable[[list[DateCandidate]], DateCandidate | None] | None = None,
) -> list[DateCandidate]:
    out = list(cands)

    def reject(i: int, rule: str) -> None:
        if out[i].rejected is None:
            out[i] = out[i].model_copy(update={"rejected": rule})

    fetched = None if fetched_at is None else fetched_at.date()
    # pass 1: each candidate on its own
    for i, c in enumerate(out):
        future = fetched is not None and c.value > fetched + dt.timedelta(days=1)
        if c.value < EARLIEST or (future and c.kind != "review_due"):  # a due date is ahead
            reject(i, "out_of_range")
        elif (
            fetched is not None
            and c.source == "http_header"
            and abs((c.value - fetched).days) <= NEAR_DAYS
        ):
            reject(i, "dynamic_header")
    # pass 2: a fresh CMS stamp needs an independent source within 7 days
    if fetched is not None:
        survivors = [c for c in out if c.rejected is None]
        for i, c in enumerate(out):
            if c.rejected or c.kind != "modified" or c.source not in STAMP_SOURCES:
                continue
            if abs((c.value - fetched).days) > NEAR_DAYS:
                continue
            backed = any(
                o.source in INDEPENDENT_SOURCES
                and o.kind in ("modified", "published", "reviewed")
                and abs((o.value - c.value).days) <= CORROBORATE_DAYS
                for o in survivors
            )
            if not backed:
                reject(i, "cms_stamp")
    # pass 3: no modified date before the published date that will be chosen
    usable = [c for c in out if c.rejected is None]
    if choose_published is not None:
        chosen = choose_published(usable)
        first = None if chosen is None else chosen.value
    else:
        published = [c.value for c in usable if c.kind == "published"]
        first = min(published) if published else None
    if first is not None:
        for i, c in enumerate(out):
            if c.kind == "modified" and c.rejected is None and c.value < first:
                reject(i, "modified_before_published")
    return out
