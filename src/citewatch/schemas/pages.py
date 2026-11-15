"""Page metadata and date candidates (Tech Spec §4, §6.2, §7.3, SCH-02)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import StringConstraints, model_validator

from ._base import Model, NonBlank, PosInt, Timestamp

DateKind = Literal["modified", "published", "reviewed", "review_due"]
DateSource = Literal[
    "schema_org", "microdata", "meta_tag", "visible_text", "sitemap", "page_age", "http_header"
]
Outcome = Literal[
    "ok",
    "robots_disallowed",
    "blocked",
    "gated",
    "not_html",
    "fetch_error",
    "too_large",
    "not_fetched",
]
Evidence = Annotated[str, StringConstraints(min_length=1, max_length=120)]


class DateCandidate(Model):
    kind: DateKind
    value: dt.date
    source: DateSource
    evidence: Evidence  # property name or matched text, at most 120 chars
    rejected: NonBlank | None = None  # the plausibility rule that rejected it


class PageMeta(Model):
    url: NonBlank
    fetched_at: Timestamp | None = None
    outcome: Outcome
    status: PosInt | None = None
    final_url: NonBlank | None = None
    candidates: tuple[DateCandidate, ...] = ()
    date_modified: dt.date | None = None
    date_published: dt.date | None = None
    date_reviewed: dt.date | None = None
    review_due: dt.date | None = None
    modified_source: DateSource | None = None
    published_source: DateSource | None = None
    reviewed_source: DateSource | None = None
    effective_date: dt.date | None = None
    effective_source: DateSource | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PageMeta:
        if self.status is not None and not 100 <= self.status <= 599:
            raise ValueError(f"status {self.status} is not an HTTP status code")
        if self.outcome == "ok" and (self.fetched_at is None or self.status is None):
            raise ValueError("an ok fetch needs fetched_at and status")
        backed = {(c.kind, c.value, c.source) for c in self.candidates if c.rejected is None}
        for kind, value, source in (
            ("modified", self.date_modified, self.modified_source),
            ("published", self.date_published, self.published_source),
            ("reviewed", self.date_reviewed, self.reviewed_source),
        ):
            if (value is None) != (source is None):
                raise ValueError(f"date_{kind} and {kind}_source must be set together")
            if value is not None and (kind, value, source) not in backed:
                raise ValueError(
                    f"date_{kind} {value} from {source} is not backed by a non-rejected candidate"
                )
        if self.review_due is not None and ("review_due", self.review_due) not in {
            (c.kind, c.value) for c in self.candidates if c.rejected is None
        }:
            raise ValueError("review_due is not backed by a non-rejected candidate")
        if self.date_modified and self.date_published and self.date_modified < self.date_published:
            raise ValueError("date_modified is before date_published")
        # §6.2: reviewed, else modified, else published
        if self.date_reviewed is not None:
            want = (self.date_reviewed, self.reviewed_source)
        elif self.date_modified is not None:
            want = (self.date_modified, self.modified_source)
        elif self.date_published is not None:
            want = (self.date_published, self.published_source)
        else:
            want = (None, None)
        if (self.effective_date, self.effective_source) != want:
            raise ValueError(
                f"effective date/source must be {want[0]} / {want[1]} (reviewed, else modified, "
                "else published)"
            )
        return self
