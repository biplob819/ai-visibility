"""A2.3 verifier pass 1 findings and the boundaries the mutants showed untested."""

import datetime as dt
import gzip
import json

import httpx
import pytest

from citewatch.dates import (
    apply_rules,
    build_page_meta,
    from_html,
    host_lastmods,
    parse_date,
    parse_sitemap,
    resolve_dates,
)
from citewatch.dates.sitemaps import MAX_SITEMAP_BYTES, sitemap_urls
from citewatch.schemas import DateCandidate
from citewatch.store import RawStore

from ..fetch.web import FakeWeb, make

FETCHED = dt.datetime(2026, 11, 15, 12, tzinfo=dt.UTC)


def c(kind, value, source):
    return DateCandidate(
        kind=kind, value=dt.date.fromisoformat(value), source=source, evidence=f"{source} {value}"
    )


def resolve(cands):
    return resolve_dates(
        "https://a.example/",
        outcome="ok",
        status=200,
        fetched_at=FETCHED,
        final_url=None,
        candidates=cands,
    )


def rej(cands):
    return {
        (x.kind, x.source, x.value.isoformat()): x.rejected for x in apply_rules(cands, FETCHED)
    }


# --- H1: never an invalid PageMeta -----------------------------------------------------------


def test_modified_is_checked_against_the_published_date_precedence_chooses():
    pm = resolve(
        [
            c("published", "2019-05-01", "meta_tag"),
            c("modified", "2023-01-01", "meta_tag"),
            c("published", "2024-06-01", "schema_org"),
        ]
    )
    assert pm.date_published == dt.date(2024, 6, 1) and pm.date_modified is None
    assert any(x.rejected == "modified_before_published" for x in pm.candidates)


def test_one_odd_page_never_stops_page_meta(tmp_path, monkeypatch):
    import citewatch.dates.pipeline as pipe

    def boom(*a, **k):
        raise ValueError("inconsistent dates")

    monkeypatch.setattr(pipe, "resolve_dates", boom)
    (m,) = build_page_meta(tmp_path, ["https://a.example/p"])
    assert m.url == "https://a.example/p" and m.effective_date is None


# --- H2, M1: order-independent, independent corroboration only --------------------------------


def test_a_build_stamp_is_rejected_whatever_the_candidate_order():
    stamp, header, pub = (
        c("modified", "2026-11-15", "schema_org"),
        c("modified", "2026-11-15", "http_header"),
        c("published", "2018-03-03", "schema_org"),
    )
    for order in ([stamp, header, pub], [header, stamp, pub], [pub, stamp, header]):
        pm = resolve(order)
        assert pm.date_modified is None and pm.effective_date == dt.date(2018, 3, 3), order


@pytest.mark.parametrize(
    ("other", "kept"),
    [
        (c("modified", "2026-11-15", "meta_tag"), False),  # the CMS's own mirror
        (c("modified", "2026-11-14", "sitemap"), False),  # often generated on request
        (c("review_due", "2026-11-20", "visible_text"), False),  # a future due date
        (c("modified", "2026-11-12", "visible_text"), True),
        (c("modified", "2026-11-09", "page_age"), True),
    ],
)
def test_only_an_independent_source_vouches_for_a_fresh_stamp(other, kept):
    r = rej([c("modified", "2026-11-15", "schema_org"), other])
    assert (r[("modified", "schema_org", "2026-11-15")] is None) is kept


def test_rule_boundaries():
    assert (
        rej([c("modified", "2026-11-13", "schema_org")])[("modified", "schema_org", "2026-11-13")]
        is None
    )  # 2 days
    assert (
        rej([c("modified", "2026-11-14", "schema_org")])[("modified", "schema_org", "2026-11-14")]
        == "cms_stamp"
    )  # 1 day
    r = rej(
        [c("modified", "2026-11-15", "schema_org"), c("modified", "2026-11-08", "visible_text")]
    )
    assert r[("modified", "schema_org", "2026-11-15")] is None  # exactly 7 days
    r = rej(
        [c("modified", "2026-11-15", "schema_org"), c("modified", "2026-11-07", "visible_text")]
    )
    assert r[("modified", "schema_org", "2026-11-15")] == "cms_stamp"  # 8 days
    assert (
        rej([c("modified", "2026-11-13", "http_header")])[("modified", "http_header", "2026-11-13")]
        is None
    )
    assert (
        rej([c("modified", "1995-01-01", "meta_tag")])[("modified", "meta_tag", "1995-01-01")]
        is None
    )
    assert (
        rej([c("modified", "1994-12-31", "meta_tag")])[("modified", "meta_tag", "1994-12-31")]
        == "out_of_range"
    )
    assert (
        rej([c("published", "2026-11-16", "meta_tag")])[("published", "meta_tag", "2026-11-16")]
        is None
    )
    assert (
        rej([c("published", "2026-11-17", "meta_tag")])[("published", "meta_tag", "2026-11-17")]
        == "out_of_range"
    )
    r = rej([c("modified", "2020-01-01", "meta_tag"), c("published", "2020-01-01", "meta_tag")])
    assert r[("modified", "meta_tag", "2020-01-01")] is None  # the same day is not before


@pytest.mark.parametrize(
    ("better", "worse"),
    [
        ("microdata", "meta_tag"),
        ("meta_tag", "visible_text"),
        ("visible_text", "sitemap"),
        ("sitemap", "page_age"),
        ("page_age", "http_header"),
        ("schema_org", "microdata"),
    ],
)
def test_each_step_of_the_precedence(better, worse):
    pm = resolve([c("modified", "2024-01-01", worse), c("modified", "2023-01-01", better)])
    assert (pm.date_modified, pm.modified_source) == (dt.date(2023, 1, 1), better)


def test_reviewed_precedence_and_duplicates_count_once():
    pm = resolve(
        [
            c("reviewed", "2024-01-01", "schema_org"),
            c("reviewed", "2023-01-01", "visible_text"),
            c("reviewed", "2023-01-01", "visible_text"),
        ]
    )
    assert pm.reviewed_source == "visible_text" and len(pm.candidates) == 2


# --- M2: only the page's own objects -----------------------------------------------------------


def kinds(html):
    return {(x.kind, x.value.isoformat(), x.source) for x in from_html(html, "https://a.example/")}


def test_nested_images_comments_citations_and_the_website_are_not_page_dates():
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "dateModified": "2026-11-01"},
            {
                "@type": "MedicalWebPage",
                "dateModified": "2025-05-05",
                "datePublished": "2020-02-02",
                "image": {"@type": "ImageObject", "datePublished": "2017-06-15"},
                "citation": [{"@type": "ScholarlyArticle", "datePublished": "1998-01-01"}],
                "comment": {"@type": "Comment", "dateModified": "2026-10-10"},
                "mainEntity": {"@type": "Article", "datePublished": "2019-09-09"},
            },
        ],
    }
    got = kinds(f'<script type="application/ld+json">{json.dumps(ld)}</script>')
    assert got == {
        ("modified", "2025-05-05", "schema_org"),
        ("published", "2020-02-02", "schema_org"),
        ("published", "2019-09-09", "schema_org"),
    }


def test_untyped_context_free_json_ld_with_control_characters_counts():
    """The WHO shape: no @context, no top-level @type, raw newlines inside strings."""
    raw = (
        '{"name":"Flu","text":"line one\nline two","author":{"@type":"Organization"},'
        '"dateModified":"2025-02-28T10:36:00.0000000+00:00"}'
    )
    assert kinds(f'<script type="application/ld+json; charset=utf-8">{raw}</script>') == {
        ("modified", "2025-02-28", "schema_org")
    }


@pytest.mark.parametrize(
    "block",
    [
        '//<![CDATA[\n{"@type":"Article","datePublished":"2021-03-03"}\n//]]>',
        '{"@type":"Article","datePublished":"2021-03-03",}',
        '{"@type":"Article","datePublished":{"@value":"2021-03-03"}}',
        '<!-- {"@type":"Article","datePublished":"2021-03-03"} -->',
    ],
)
def test_json_ld_wrappers_and_value_objects(block):
    assert ("published", "2021-03-03", "schema_org") in kinds(
        f'<script type="application/ld+json">{block}</script>'
    )


def test_deep_nesting_never_loses_the_other_sources():
    deep = "[" * 6000 + "]" * 6000
    html = (
        f'<script type="application/ld+json">{deep}</script>'
        '<meta property="article:published_time" content="2020-01-01">'
    )
    assert ("published", "2020-01-01", "meta_tag") in kinds(html)


# --- M3: nothing ambiguous or invented ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("05/10/2024", None),
        ("16/10/2024", "2024-10-16"),
        ("12/19/2025", "2025-12-19"),
        ("03.04.2024", None),
        ("2019", None),
        ("June 2024", None),
        ("Monday, 3 June 2024", "2024-06-03"),
        ("2026-07-10T00:01:05+01:00", "2026-07-10"),
    ],
)
def test_ambiguous_and_partial_dates_are_dropped(text, value):
    got = parse_date(text)
    assert (None if got is None else got.isoformat()) == value


def test_text_meta_rdfa_and_http_equiv():
    got = kinds(
        '<meta http-equiv="last-modified" content="2024-02-02">'
        '<div vocab="http://ogp.me/ns#" typeof="Article">'
        '<span property="og:updated_time" content="2026-11-15"></span></div>'
        "<p>Updated on Monday, 3 June 2024</p>"
    )
    assert ("modified", "2024-02-02", "meta_tag") in got and (
        "modified",
        "2024-06-03",
        "visible_text",
    ) in got
    assert not any(src == "microdata" for _, _, src in got)  # Open Graph in RDFa is not schema.org


# --- DAT-05: sitemaps --------------------------------------------------------------------------


def _robots(text):
    return httpx.Response(200, content=("User-agent: *\nAllow: /\n" + text).encode())


URLS = b"<urlset><url><loc>https://a.example/p</loc><lastmod>2025-07-01</lastmod></url></urlset>"


def test_only_sitemap_lines_name_sitemaps(tmp_path):
    store = RawStore(tmp_path)
    web = FakeWeb(
        {
            "https://a.example/robots.txt": _robots(
                "Disallow: https://a.example/x.xml\nSitemap: https://a.example/s.xml\n"
            )
        }
    )
    client, _l, _ = make(tmp_path, web, store=store)
    client.get("https://a.example/p")
    assert sitemap_urls(store, "https://a.example") == ["https://a.example/s.xml"]


def test_one_index_level_and_a_new_client_reuses_the_cache(tmp_path):
    store = RawStore(tmp_path)
    idx = b"<sitemapindex><sitemap><loc>https://a.example/i2.xml</loc></sitemap></sitemapindex>"
    idx2 = b"<sitemapindex><sitemap><loc>https://a.example/deep.xml</loc></sitemap></sitemapindex>"
    web = FakeWeb(
        {
            "https://a.example/robots.txt": _robots(
                "Sitemap: https://a.example/i1.xml\nSitemap: https://a.example/s.xml\n"
            ),
            "https://a.example/i1.xml": httpx.Response(200, content=idx),
            "https://a.example/i2.xml": httpx.Response(200, content=idx2),
            "https://a.example/s.xml": httpx.Response(200, content=URLS),
        }
    )
    client, _l, _ = make(tmp_path, web, store=store)
    client.get("https://a.example/p")
    assert host_lastmods(client, store, "https://a.example") == {
        "https://a.example/p": "2025-07-01"
    }
    assert "https://a.example/deep.xml" not in web.urls()
    web2 = FakeWeb()
    fresh, _l2, _ = make(tmp_path / "r2", web2, store=store)
    assert host_lastmods(fresh, store, "https://a.example") == {"https://a.example/p": "2025-07-01"}
    assert web2.requests == []


def test_a_temporary_failure_is_not_cached(tmp_path):
    store = RawStore(tmp_path)
    web = FakeWeb(
        {
            "https://a.example/robots.txt": _robots("Sitemap: https://a.example/s.xml\n"),
            "https://a.example/s.xml": [httpx.Response(503)] * 3,
        }
    )
    client, _l, _ = make(tmp_path, web, store=store)
    client.get("https://a.example/p")
    assert host_lastmods(client, store, "https://a.example") == {}
    web2 = FakeWeb({"https://a.example/s.xml": httpx.Response(200, content=URLS)})
    later, _l2, _ = make(tmp_path / "r2", web2, store=store)
    assert host_lastmods(later, store, "https://a.example") == {"https://a.example/p": "2025-07-01"}


def test_the_decoded_cap_and_multi_member_gzip():
    pad = MAX_SITEMAP_BYTES - len(URLS)
    exact = gzip.compress(URLS[:-9] + b" " * pad + URLS[-9:])
    assert parse_sitemap(exact)[0] == {"https://a.example/p": "2025-07-01"}
    over = gzip.compress(URLS[:-9] + b" " * (pad + 1) + URLS[-9:])
    assert parse_sitemap(over) == ({}, [])
    two = gzip.compress(URLS[:30]) + gzip.compress(URLS[30:])
    assert parse_sitemap(two)[0] == {"https://a.example/p": "2025-07-01"}
