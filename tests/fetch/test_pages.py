"""FET-05, FET-06: once across runs, HTML only, 5 MB, bodies in memory only."""

import gzip
import json

import httpx
import pytest

from citewatch.fetch import fetch_key, fetch_pages, main_text
from citewatch.store import RawStore

from .web import HTML, FakeWeb, audit, make

pytestmark = pytest.mark.polite


def test_each_url_is_fetched_once_across_runs(tmp_path):
    store = RawStore(tmp_path)
    urls = [
        "https://a.example/1",
        "https://a.example/2",
        "https://b.example/1",
        "https://a.example/1",
    ]
    web = FakeWeb()
    client, log, _ = make(tmp_path, web, store=store)
    res = fetch_pages(urls, client=client, store=store)
    assert res.fetched == 3 and res.outcomes["ok"] == 3
    web2 = FakeWeb()
    client2, log2, _ = make(tmp_path, web2, store=store)
    again = fetch_pages([*urls, "https://c.example/new"], client=client2, store=store)
    assert again.cached == 3 and again.fetched == 1
    assert [u for u in web2.urls() if "c.example" not in u] == []
    assert audit(log) == [] and audit(log2) == []


def test_only_html_is_read_and_large_pages_are_cut(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/doc.pdf": httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7" * 1000
            ),
            "https://a.example/big": httpx.Response(
                200, headers=HTML, content=b"<html>" + b"x" * 5000
            ),
        }
    )
    store = RawStore(tmp_path)
    client, log, _ = make(tmp_path, web, store=store, max_page_bytes=1000)
    seen = []
    fetch_pages(
        ["https://a.example/doc.pdf", "https://a.example/big"],
        client=client,
        store=store,
        analyse=lambda p: seen.append(p.url) or {},
    )
    pdf = store.get("fetch", fetch_key("https://a.example/doc.pdf"))
    big = store.get("fetch", fetch_key("https://a.example/big"))
    assert pdf["outcome"] == "not_html" and big["outcome"] == "too_large" and seen == []
    rows = {r["url"]: r for r in log.rows()}
    assert rows["https://a.example/doc.pdf"]["bytes"] == 0
    assert rows["https://a.example/big"]["bytes"] == 1001  # read one byte past the cap, no more
    assert audit(log) == []


def test_the_store_never_holds_a_body_and_analyse_sees_it_in_memory(tmp_path):
    body = (
        b"<html><head><script>var secret=1</script></head>"
        b"<body><h1>Title</h1><p>Text here.</p></body></html>"
    )
    web = FakeWeb({"https://a.example/p": httpx.Response(200, headers=HTML, content=body)})
    store = RawStore(tmp_path)
    client, _log, _ = make(tmp_path, web, store=store)
    got = {}

    def analyse(page):
        got["html"] = page.html
        return {"candidates": []}

    fetch_pages(["https://a.example/p"], client=client, store=store, analyse=analyse)
    assert "<h1>Title</h1>" in got["html"]
    raw = b"".join(
        gzip.decompress(p.read_bytes()) for p in (tmp_path / "data" / "raw").rglob("*.gz")
    )
    assert b"<html" not in raw.lower() and b"Text here" not in raw
    rec = store.get("fetch", fetch_key("https://a.example/p"))
    assert not {"body", "html", "page_text"} & set(rec) and rec["candidates"] == []


def test_only_support_sample_pages_keep_their_main_text(tmp_path):
    body = (
        b"<html><head><style>p{}</style></head><body><nav>Menu</nav>"
        b"<p>Keep  this.</p><script>x()</script></body></html>"
    )
    web = FakeWeb({"https://a.example/s": httpx.Response(200, headers=HTML, content=body)})
    store = RawStore(tmp_path)
    cache = tmp_path / "bodies"
    client, _log, _ = make(tmp_path, web, store=store)
    fetch_pages(
        ["https://a.example/s", "https://a.example/other"],
        client=client,
        store=store,
        keep_text=frozenset({"https://a.example/s"}),
        body_cache=cache,
    )
    files = [f for f in cache.iterdir() if f.name != ".citewatch-body-cache"]
    assert (cache / ".citewatch-body-cache").is_file()  # finalise deletes only marked caches
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert text == "Menu\nKeep this." or "Keep this." in text
    assert "x()" not in text and "p{}" not in text and "<" not in text


def test_an_analyse_bug_never_loses_the_fetch_record(tmp_path):
    store = RawStore(tmp_path)
    client, _log, _ = make(tmp_path, FakeWeb(), store=store)

    def broken(page):
        raise RuntimeError("date parser bug")

    res = fetch_pages(["https://a.example/p"], client=client, store=store, analyse=broken)
    rec = store.get("fetch", fetch_key("https://a.example/p"))
    assert res.fetched == 1 and rec["outcome"] == "ok" and "RuntimeError" in rec["analyse_error"]


def test_main_text_drops_markup():
    assert main_text("<p>a <b>b</b></p><script>c</script><style>d</style>") == "a b"
    assert json.dumps(main_text("<p>&amp; &lt;x&gt;</p>")) == json.dumps("& <x>")
