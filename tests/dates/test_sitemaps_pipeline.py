"""DAT-05, and the fetch stage writing page_meta.jsonl."""

import datetime as dt
import gzip
import json

import httpx
import pytest

import storage_audit
from citewatch.dates import build_page_meta, host_lastmods, parse_sitemap
from citewatch.dates.pipeline import analyse
from citewatch.fetch import fetch_pages
from citewatch.store import RawStore

from ..fetch.web import HTML, FakeWeb, audit, make

pytestmark = pytest.mark.polite

URLSET = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://a.example/p</loc><lastmod>2025-07-01</lastmod></url>
<url><loc>https://a.example/q?utm_source=x</loc><lastmod>2025-07-02</lastmod></url>
<url><loc>https://other.example/z</loc><lastmod>2025-07-03</lastmod></url></urlset>"""
INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://a.example/s1.xml</loc></sitemap></sitemapindex>"""


def robots(lines):
    return httpx.Response(200, content=("User-agent: *\nAllow: /\n" + lines).encode())


def test_lastmod_comes_only_from_sitemaps_listed_in_robots(tmp_path):
    store = RawStore(tmp_path)
    web = FakeWeb(
        {
            "https://a.example/robots.txt": robots("Sitemap: https://a.example/index.xml\n"),
            "https://a.example/index.xml": httpx.Response(200, content=INDEX),
            "https://a.example/s1.xml": httpx.Response(200, content=gzip.compress(URLSET)),
            "https://a.example/sitemap.xml": httpx.Response(200, content=URLSET),
        }
    )
    client, log, _ = make(tmp_path, web, store=store)
    client.get("https://a.example/p")
    got = host_lastmods(client, store, "https://a.example")
    assert got == {"https://a.example/p": "2025-07-01", "https://a.example/q": "2025-07-02"}
    assert "https://a.example/sitemap.xml" not in web.urls()  # never guessed
    n = len(web.requests)
    assert (
        host_lastmods(client, store, "https://a.example") == got and len(web.requests) == n
    )  # cached
    assert audit(log) == []


def test_a_host_without_listed_sitemaps_is_asked_nothing(tmp_path):
    store = RawStore(tmp_path)
    web = FakeWeb({"https://a.example/robots.txt": robots("")})
    client, _log, _ = make(tmp_path, web, store=store)
    client.get("https://a.example/p")
    n = len(web.requests)
    assert host_lastmods(client, store, "https://a.example") == {} and len(web.requests) == n


def test_hostile_and_oversized_sitemaps_are_no_sitemap():
    bomb = b"""<?xml version="1.0"?>
<!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>
<urlset><url><loc>https://a.example/&b;</loc><lastmod>2025-01-01</lastmod></url></urlset>"""
    assert parse_sitemap(bomb) == ({}, [])
    assert parse_sitemap(b"not xml") == ({}, [])
    big = gzip.compress(b"<urlset>" + b" " * (11 * 1024 * 1024) + b"</urlset>")
    assert parse_sitemap(big) == ({}, [])


def test_sitemap_requests_follow_robots(tmp_path):
    store = RawStore(tmp_path)
    web = FakeWeb(
        {
            "https://a.example/robots.txt": robots(
                "Disallow: /maps/\nSitemap: https://a.example/maps/s.xml\n"
            )
        }
    )
    client, log, _ = make(tmp_path, web, store=store)
    client.get("https://a.example/p")
    assert host_lastmods(client, store, "https://a.example") == {}
    assert "https://a.example/maps/s.xml" not in web.urls() and audit(log) == []


def test_the_fetch_stage_keeps_candidates_and_page_meta_resolves(tmp_path):
    store = RawStore(tmp_path)
    page = (
        b'<html><head><meta property="article:published_time" content="2020-01-01"></head>'
        b"<body><p>Page last reviewed: 12 March 2024</p></body></html>"
    )
    web = FakeWeb(
        {
            "https://a.example/p": httpx.Response(
                200,
                headers={**HTML, "last-modified": "Sun, 01 Mar 2026 10:00:00 GMT"},
                content=page,
            )
        }
    )
    client, _log, _ = make(tmp_path, web, store=store)
    fetch_pages(["https://a.example/p"], client=client, store=store, analyse=analyse)
    data = tmp_path / "data"
    (data / "answers.jsonl").write_text(
        json.dumps(
            {
                "run": 1,
                "question_id": "q-001",
                "model": "claude-sonnet-5-5",
                "answered_at": "2026-11-15T10:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (data / "consulted.jsonl").write_text(
        json.dumps(
            {
                "run": 1,
                "question_id": "q-001",
                "model": "claude-sonnet-5-5",
                "url": "https://a.example/p",
                "page_age": "10 days ago",
            }
        )
        + "\n"
        + json.dumps(
            {
                "run": 1,
                "question_id": "q-001",
                "model": "claude-sonnet-5-5",
                "url": "https://b.example/blocked",
                "page_age": "30 days ago",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    metas = {
        m.url: m
        for m in build_page_meta(
            tmp_path,
            ["https://a.example/p", "https://b.example/blocked"],
            {"https://a.example/p": "2025-05-05"},
        )
    }
    m = metas["https://a.example/p"]
    assert m.date_reviewed == dt.date(2024, 3, 12) and m.date_published == dt.date(2020, 1, 1)
    assert {c.source for c in m.candidates} == {
        "meta_tag",
        "visible_text",
        "http_header",
        "sitemap",
        "page_age",
    }
    b = metas["https://b.example/blocked"]
    assert (
        b.outcome == "not_fetched"
        and b.effective_date == dt.date(2026, 10, 16)
        and b.effective_source == "page_age"
    )
    for f in (tmp_path / "data" / "raw").rglob("*.gz"):
        assert storage_audit.file_problems(f, tmp_path) == []
