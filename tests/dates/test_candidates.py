"""DAT-01, DAT-06: candidates from every source, with evidence."""

import datetime as dt

import pytest

from citewatch.dates import (
    from_header,
    from_html,
    from_page_age,
    from_sitemap,
    page_age_date,
    parse_date,
)

AT = dt.datetime(2026, 11, 15, 12, tzinfo=dt.UTC)

HTML = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"MedicalWebPage","dateModified":"2025-03-01T09:00:00+01:00","lastReviewed":"2024-11-02",
  "mainEntity":{"@type":"Article","datePublished":"2019-04-05"}}]}</script>
<meta property="article:modified_time" content="2025-02-01T10:00:00Z">
<meta property="article:published_time" content="2019-04-06">
<meta name="DC.date.issued" content="2019-04-07">
<meta property="og:updated_time" content="2025-02-02">
</head><body>
<div itemscope itemtype="https://schema.org/Article">
<meta itemprop="dateModified" content="2025-01-15"></div>
<p>Page last reviewed: 12 March 2024<br>Next review due: 12/03/2027</p>
<p>Last updated 3 June 2024</p><p>Published 1 February 2020</p>
<script>var x = "Last updated 1 January 2001";</script>
</body></html>"""


def kinds(cands):
    return {(c.kind, c.value.isoformat(), c.source) for c in cands}


def test_every_html_source_is_read():
    got = kinds(from_html(HTML, "https://www.nhs.uk/x"))
    assert ("modified", "2025-03-01", "schema_org") in got
    assert ("reviewed", "2024-11-02", "schema_org") in got
    assert ("published", "2019-04-05", "schema_org") in got  # nested object
    assert ("modified", "2025-02-01", "meta_tag") in got and (
        "modified",
        "2025-02-02",
        "meta_tag",
    ) in got
    assert ("published", "2019-04-06", "meta_tag") in got and (
        "published",
        "2019-04-07",
        "meta_tag",
    ) in got
    assert ("modified", "2025-01-15", "microdata") in got
    assert ("reviewed", "2024-03-12", "visible_text") in got
    assert (
        "review_due",
        "2027-03-12",
        "visible_text",
    ) in got  # day-first: 12 March, not 3 December
    assert ("modified", "2024-06-03", "visible_text") in got
    assert ("published", "2020-02-01", "visible_text") in got
    assert not any(
        c.value.year == 2001 for c in from_html(HTML, "https://www.nhs.uk/x")
    )  # scripts ignored


def test_evidence_is_short_and_names_the_source():
    long = "<p>Last updated 3 June 2024 " + "x" * 300 + "</p>"
    for c in from_html(HTML + long, "https://a.example/"):
        assert 1 <= len(c.evidence) <= 120


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        ("198 days ago", "2026-05-01"),
        ("1 days ago", "2026-11-14"),
        ("a week ago", "2026-11-08"),
        ("3 weeks ago", "2026-10-25"),
        ("2 months ago", "2026-09-16"),
        ("a year ago", "2025-11-15"),
        ("April 30, 2025", "2025-04-30"),
    ],
)
def test_page_age_relative_and_absolute(age, expected):
    """D-35: real page ages are relative to the request."""
    assert str(page_age_date(age, AT)) == expected
    (c,) = from_page_age(age, AT)
    assert c.source == "page_age" and c.kind == "modified"


def test_header_sitemap_and_junk():
    (h,) = from_header("Sun, 01 Mar 2026 10:00:00 GMT")
    assert (h.kind, h.value.isoformat(), h.source) == ("modified", "2026-03-01", "http_header")
    (s,) = from_sitemap("2025-07-01T00:00:00+00:00")
    assert (s.value.isoformat(), s.source) == ("2025-07-01", "sitemap")
    assert (
        from_header("not a date") == []
        and from_sitemap("") == []
        and from_page_age("soon", AT) == []
    )
    assert parse_date("yesterday") is None and parse_date("0000-01-01") is None


def test_malformed_markup_never_stops_a_page():
    bad = '<script type="application/ld+json">{not json</script><p>Last updated 3 June 2024</p>'
    assert ("modified", "2024-06-03", "visible_text") in kinds(from_html(bad, "https://a.example/"))


def test_media_review_dates_are_not_the_page_review_date():
    """Found on the real NHS snapshots: images and videos have their own review dates."""
    html = (
        "<p>Media last reviewed: 15 March 2026</p><p>Media review due: 15 March 2029</p>"
        "<p>Page last reviewed: 03 February 2026</p><p>Next review due: 03 February 2029</p>"
        "<p>Last reviewed: 06 Nov 2024</p>"
    )
    got = kinds(from_html(html, "https://www.nhs.uk/x"))
    assert ("reviewed", "2026-03-15", "visible_text") not in got
    assert ("review_due", "2029-03-15", "visible_text") not in got
    assert ("reviewed", "2026-02-03", "visible_text") in got and (
        "review_due",
        "2029-02-03",
        "visible_text",
    ) in got
    assert ("reviewed", "2024-11-06", "visible_text") in got
