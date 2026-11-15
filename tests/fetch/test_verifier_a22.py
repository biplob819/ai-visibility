"""A2.2 verifier pass 1 findings, each pinned (no network)."""

import datetime as dt
import gzip
import itertools
import time

import httpx
import pytest

import storage_audit
from citewatch.fetch import PageHistory, fetch_pages, rate
from citewatch.fetch.client import is_gated
from citewatch.store import RawStore

from .web import HTML, PAGE, FakeWeb, VClock, audit, make

pytestmark = pytest.mark.polite


def test_a_run_right_after_another_waits_for_each_host(tmp_path):
    """H1: the limiter is seeded with each host's last request from earlier logs."""
    clock = VClock()
    c1, log, _ = make(tmp_path, FakeWeb(), vclock=clock)
    c1.get("https://a.example/1")
    history = PageHistory.from_logs([log.path])
    c2, log2, _ = make(tmp_path, FakeWeb(), vclock=clock, history=history)
    assert log2.path == log.path
    c2.get("https://a.example/2")  # robots is already known; the page waits its turn
    assert audit(log) == []


def test_a_soft_404_html_robots_is_never_stored(tmp_path):
    """H2: only directive lines reach the store."""
    html = b"<!doctype html><html><body><p>Not found</p>Disallow: /x</body></html>"
    store = RawStore(tmp_path)
    web = FakeWeb({"https://a.example/robots.txt": httpx.Response(200, headers=HTML, content=html)})
    client, _log, _ = make(tmp_path, web, store=store)
    assert client.get("https://a.example/p").outcome == "ok"
    for f in (tmp_path / "data" / "raw").rglob("*.gz"):
        raw = gzip.decompress(f.read_bytes())
        assert b"<" not in raw and b"doctype" not in raw.lower()
        assert storage_audit.file_problems(f, tmp_path) == []


@pytest.mark.parametrize(
    "routes",
    [
        {"https://a.example/robots.txt": httpx.Response(301, headers={"location": "/robots.txt"})},
        {
            "https://a.example/robots.txt": httpx.Response(
                301, headers={"location": "http://a.example/robots.txt"}
            ),
            "http://a.example/robots.txt": httpx.Response(
                301, headers={"location": "https://a.example/robots.txt"}
            ),
        },
        {
            "https://a.example/robots.txt": httpx.Response(
                302, headers={"location": "file:///robots.txt"}
            )
        },
    ],
)
def test_robots_loops_and_odd_schemes_disallow_within_budget(tmp_path, routes):
    """M3, M4: no more than 3 requests for one robots.txt; file: is never followed."""
    web = FakeWeb(routes)
    client, log, _ = make(tmp_path, web)
    outs = [client.get(f"https://a.example/p{i}").outcome for i in range(4)]
    assert outs == ["robots_disallowed"] * 4
    assert len(web.requests) <= 3
    assert audit(log) == []


def test_the_whole_request_has_a_deadline(tmp_path):
    """M5: a server that stalls (slow headers) cannot hold one get for minutes."""

    def stall(request):
        time.sleep(2.0)
        return httpx.Response(200, headers=HTML, content=PAGE)

    web = FakeWeb({"https://a.example/slow": stall})
    client, log, _ = make(tmp_path, web, timeout=0.2)
    start = time.monotonic()
    r = client.get("https://a.example/slow")
    assert r.outcome == "fetch_error" and "timeout" in (r.detail or "")
    assert time.monotonic() - start < 3 * (0.2 + 1.0) + 1.0
    assert audit(log) == []


def test_cookies_are_never_sent_back(tmp_path):
    """M6: each request has its own client; a Set-Cookie never returns."""
    web = FakeWeb(
        {
            "https://a.example/1": httpx.Response(
                200, headers={**HTML, "set-cookie": "sid=abc; Path=/"}, content=PAGE
            )
        }
    )
    client, _log, _ = make(tmp_path, web)
    client.get("https://a.example/1")
    client.get("https://a.example/2")
    assert all("cookie" not in r.headers for r in web.requests)


@pytest.mark.parametrize(
    ("start", "location", "final"),
    [
        ("https://a.example/dir", "/dir/", "https://a.example/dir/"),
        ("http://a.example/p", "https://a.example/p", "https://a.example/p"),
    ],
)
def test_redirects_to_the_same_page_are_followed(tmp_path, start, location, final):
    """M7: the commonest redirects end ok, not in a replayed 301."""
    web = FakeWeb({start: httpx.Response(301, headers={"location": location})})
    client, log, _ = make(tmp_path, web)
    r = client.get(start)
    assert r.outcome == "ok" and r.final_url == final
    assert audit(log) == []


def test_a_503_retry_after_is_honoured(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/p": [
                httpx.Response(503, headers={"retry-after": "30"}),
                httpx.Response(200, headers=HTML, content=PAGE),
            ]
        }
    )
    client, _log, clock = make(tmp_path, web)
    before = clock.now()
    assert client.get("https://a.example/p").outcome == "ok" and clock.now() - before >= 30
    web2 = FakeWeb({"https://a.example/q": httpx.Response(503, headers={"retry-after": "3600"})})
    c2, _l, _ = make(tmp_path / "b", web2)
    c2.get("https://a.example/q")
    assert web2.urls().count("https://a.example/q") == 1


def test_a_redirect_carrying_credentials_is_not_followed(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/p": httpx.Response(
                302, headers={"location": "https://u:pw@b.example/"}
            )
        }
    )
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/p").detail == "redirect carrying credentials"
    assert all("authorization" not in r.headers for r in web.requests)
    assert not any("b.example" in u for u in web.urls())


def test_gating_ignores_comments_and_reads_either_attribute_order():
    assert not is_gated(b'<html><!-- <input type="password"> --><p>free</p></html>')
    assert is_gated(b'<html><meta content="false" itemprop="isAccessibleForFree"></html>')


def test_a_torn_log_line_never_stops_later_fetches(tmp_path):
    p = tmp_path / "fetch_log.jsonl"
    p.write_text(
        '{"url": "https://a.example/p", "status": 403, "outcome": "blocked", '
        '"at": "2026-11-15T12:00:00Z"}\n{"url": "https://a.ex',
        encoding="utf-8",
    )
    h = PageHistory.from_logs([p])
    assert h.may_request("https://a.example/p") == "blocked earlier"
    assert "a.example" in h.last_at


def test_politeness_constants_are_pinned():
    assert rate.INTERVAL_S == 1.0 and rate.MARGIN_S >= 0.01 and rate.MAX_IN_FLIGHT == 8
    from citewatch.fetch import client, pages

    assert client.MAX_RETRIES == 2 and pages.MAX_HOSTS_IN_FLIGHT == 8
    assert client.MAX_PAGE_BYTES == 5 * 1024 * 1024 and client.TIMEOUT_S == 10.0


def test_the_cap_reads_at_most_one_byte_past_the_limit(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/big": httpx.Response(
                200, headers=HTML, content=b"<html>" + b"x" * 50_000
            )
        }
    )
    store = RawStore(tmp_path)
    client, log, _ = make(tmp_path, web, store=store, max_page_bytes=1000)
    fetch_pages(["https://a.example/big"], client=client, store=store)
    row = next(r for r in log.rows() if r["url"].endswith("/big"))
    assert row["bytes"] == 1001 and row["outcome"] == "too_large"


def test_stalled_hosts_never_bunch_up_requests_to_healthy_ones(tmp_path):
    """v2 H-1: requests stuck past the deadline (e.g. DNS) never delay or bunch later ones."""
    import threading

    from citewatch.fetch import FetchLog, HostLimiter, PoliteClient

    arrivals: list[float] = []
    lock = threading.Lock()

    def handler(request):
        if request.url.host.startswith("dead"):
            time.sleep(8.0)
        elif request.url.host == "good.example" and request.url.path != "/robots.txt":
            with lock:
                arrivals.append(time.monotonic())
        return httpx.Response(
            404 if request.url.path == "/robots.txt" else 200, headers=HTML, content=PAGE
        )

    log = FetchLog(tmp_path / "fetch_log.jsonl")
    client = PoliteClient(
        "citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)",
        log,
        limiter=HostLimiter(interval=0.3, margin=0.02),
        transport=httpx.MockTransport(handler),
        timeout=0.2,
    )
    urls = [f"https://good.example/{i}" for i in range(20)] + [
        f"https://dead{i}.example/p" for i in range(40)
    ]
    fetch_pages(urls, client=client, store=RawStore(tmp_path))
    assert len(arrivals) == 20
    gaps = [b - a for a, b in itertools.pairwise(arrivals)]
    assert min(gaps) >= 0.25, gaps  # spaced on the wire, not only in the log


def test_a_pause_between_clock_reads_never_shrinks_logged_gaps():
    """v2 M-1: the logged `at` is the wall time the spacing was checked against."""
    from citewatch.fetch import HostLimiter

    from .web import BASE

    clock = VClock()
    first = {"done": False}

    def wall():
        if not first["done"]:
            first["done"] = True
            return BASE + dt.timedelta(seconds=clock.now() + 0.1)  # the process paused here
        return BASE + dt.timedelta(seconds=clock.now())

    lim = HostLimiter(clock=clock.now, sleep=clock.sleep, wall=wall)
    ats = []
    for _ in range(3):
        with lim.request("a.example") as at:
            ats.append(at)
    assert all((b - a).total_seconds() >= 1.0 for a, b in itertools.pairwise(ats))


def test_stored_robots_directives_never_carry_markup():
    from citewatch.fetch.robots import directives, rules_from

    lines = directives("Sitemap: <a href=x> <body>\nUser-agent: *\nDisallow: /<html>/\n")
    assert not any("<" in x or ">" in x for x in lines)
    r = rules_from(200, "\n".join(lines))
    assert not r.allows("https://a.example/%3Chtml%3E/x")


def test_sibling_studies_share_the_fetch_history(tmp_path):
    from citewatch.cli import fetch_logs_for

    for s in ("a", "b"):
        (tmp_path / "studies" / s / "data").mkdir(parents=True)
    (tmp_path / "studies" / "a" / "data" / "fetch_log.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "studies" / "b" / "data" / "old").mkdir()
    (tmp_path / "studies" / "b" / "data" / "old" / "fetch_log.1.jsonl.gz").write_bytes(
        gzip.compress(b"")
    )
    logs = fetch_logs_for(tmp_path / "studies" / "b")
    assert {p.parent.parent.name if p.parent.name == "data" else "b" for p in logs} == {"a", "b"}
    assert len(logs) == 2
    lone = tmp_path / "lone"
    (lone / "data").mkdir(parents=True)
    assert fetch_logs_for(lone) == []


def test_an_international_name_and_its_punycode_are_one_host(tmp_path):
    """v2 M-4: one rate bucket and one robots.txt for both spellings."""
    web = FakeWeb(
        {
            "https://xn--bcher-kva.example/a": httpx.Response(
                301, headers={"location": "https://xn--bcher-kva.example/b"}
            )
        }
    )
    client, log, _ = make(tmp_path, web)
    client.get("https://bücher.example/a")
    client.get("https://xn--bcher-kva.example/c")
    assert [u for u in web.urls() if u.endswith("/robots.txt")] == [
        "https://xn--bcher-kva.example/robots.txt"
    ]
    ats = [dt.datetime.fromisoformat(r["at"]) for r in log.rows()]
    assert all((b - a).total_seconds() >= 1.0 for a, b in itertools.pairwise(ats))


def test_robots_requests_respect_the_page_budget(tmp_path):
    h = PageHistory()
    for _ in range(3):
        h.seed(
            {
                "url": "https://a.example/robots.txt",
                "status": 503,
                "outcome": "fetch_error",
                "at": "2026-11-15T11:00:00Z",
            }
        )
    web = FakeWeb()
    client, _log, _ = make(tmp_path, web, history=h)
    assert client.get("https://a.example/p").outcome == "robots_disallowed"
    assert web.requests == []


def test_archived_gz_logs_seed_the_history(tmp_path):
    p = tmp_path / "fetch_log.1.jsonl.gz"
    row = (
        b'{"url": "https://a.example/p", "status": 451, "outcome": "blocked", '
        b'"at": "2026-11-15T12:00:00Z"}\n'
    )
    p.write_bytes(gzip.compress(row))
    assert PageHistory.from_logs([p]).may_request("https://a.example/p") == "blocked earlier"
