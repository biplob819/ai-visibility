"""DAT-02, DAT-03, DAT-06: rules, precedence and the chosen dates."""

import datetime as dt

from citewatch.dates import apply_rules, resolve_dates
from citewatch.schemas import DateCandidate

FETCHED = dt.datetime(2026, 11, 15, 12, tzinfo=dt.UTC)


def c(kind, value, source):
    return DateCandidate(
        kind=kind, value=dt.date.fromisoformat(value), source=source, evidence=f"{source} {value}"
    )


def rejected(cands):
    return {(x.source, x.value.isoformat()): x.rejected for x in cands}


def test_out_of_range_dates_are_rejected_but_kept():
    out = apply_rules(
        [
            c("modified", "1994-12-31", "meta_tag"),
            c("modified", "2026-11-17", "schema_org"),
            c("review_due", "2028-01-01", "visible_text"),
        ],
        FETCHED,
    )
    r = rejected(out)
    assert (
        r[("meta_tag", "1994-12-31")] == "out_of_range"
        and r[("schema_org", "2026-11-17")] == "out_of_range"
    )
    assert r[("visible_text", "2028-01-01")] is None and len(out) == 3  # a due date is ahead


def test_a_fresh_last_modified_header_is_dynamic():
    r = rejected(
        apply_rules(
            [
                c("modified", "2026-11-15", "http_header"),
                c("modified", "2026-11-10", "http_header"),
            ],
            FETCHED,
        )
    )
    assert (
        r[("http_header", "2026-11-15")] == "dynamic_header"
        and r[("http_header", "2026-11-10")] is None
    )


def test_a_lone_fresh_cms_stamp_is_rejected_but_a_corroborated_one_is_kept():
    alone = rejected(
        apply_rules(
            [c("modified", "2026-11-15", "schema_org"), c("published", "2020-01-01", "meta_tag")],
            FETCHED,
        )
    )
    assert alone[("schema_org", "2026-11-15")] == "cms_stamp"
    backed = rejected(
        apply_rules(
            [
                c("modified", "2026-11-15", "schema_org"),
                c("modified", "2026-11-12", "visible_text"),
            ],
            FETCHED,
        )
    )
    assert backed[("schema_org", "2026-11-15")] is None


def test_a_modified_date_before_publication_is_rejected():
    r = rejected(
        apply_rules(
            [c("modified", "2019-01-01", "meta_tag"), c("published", "2020-01-01", "schema_org")],
            FETCHED,
        )
    )
    assert r[("meta_tag", "2019-01-01")] == "modified_before_published"


def test_precedence_and_effective_date():
    cands = [
        c("modified", "2024-01-01", "http_header"),
        c("modified", "2025-01-01", "visible_text"),
        c("modified", "2025-02-01", "meta_tag"),
        c("modified", "2025-03-01", "schema_org"),
        c("modified", "2025-04-01", "schema_org"),
        c("published", "2019-01-01", "meta_tag"),
        c("published", "2018-06-01", "meta_tag"),
        c("reviewed", "2024-05-05", "schema_org"),
        c("reviewed", "2024-06-06", "visible_text"),
        c("review_due", "2027-06-06", "visible_text"),
    ]
    pm = resolve_dates(
        "https://a.example/",
        outcome="ok",
        status=200,
        fetched_at=FETCHED,
        final_url=None,
        candidates=cands,
    )
    assert (str(pm.date_modified), pm.modified_source) == (
        "2025-04-01",
        "schema_org",
    )  # latest within source
    assert (str(pm.date_published), pm.published_source) == (
        "2018-06-01",
        "meta_tag",
    )  # earliest
    assert (str(pm.date_reviewed), pm.reviewed_source) == ("2024-06-06", "visible_text")
    assert str(pm.review_due) == "2027-06-06"
    assert (pm.effective_date, pm.effective_source) == (pm.date_reviewed, "visible_text")
    assert len(pm.candidates) == len(cands)


def test_effective_falls_back_and_a_blocked_page_can_use_page_age():
    pm = resolve_dates(
        "https://a.example/",
        outcome="blocked",
        status=403,
        fetched_at=FETCHED,
        final_url=None,
        candidates=[c("modified", "2026-05-01", "page_age")],
    )
    assert (str(pm.effective_date), pm.effective_source) == ("2026-05-01", "page_age")
    none = resolve_dates(
        "https://a.example/",
        outcome="ok",
        status=200,
        fetched_at=FETCHED,
        final_url=None,
        candidates=[],
    )
    assert none.effective_date is None and none.effective_source is None


def test_rejected_candidates_are_never_chosen():
    pm = resolve_dates(
        "https://a.example/",
        outcome="ok",
        status=200,
        fetched_at=FETCHED,
        final_url=None,
        candidates=[
            c("modified", "2026-11-15", "http_header"),
            c("modified", "2023-01-01", "page_age"),
        ],
    )
    assert (str(pm.date_modified), pm.modified_source) == ("2023-01-01", "page_age")
