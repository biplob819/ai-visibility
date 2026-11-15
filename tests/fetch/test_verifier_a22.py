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
        assert b"<" not in raw  # encoded, never markup
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


# --- pass 3 -------------------------------------------------------------------------------


def test_a_slow_first_connection_never_shrinks_the_gap_on_the_wire(tmp_path, monkeypatch):
    """v3 M1: the next request is spaced from when the last one actually left."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpcore._backends.sync as backend

    from citewatch.fetch import FetchLog, PoliteClient

    seen: list[float] = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            seen.append(time.monotonic())
            body = b"" if self.path == "/robots.txt" else PAGE
            self.send_response(404 if self.path == "/robots.txt" else 200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = backend.SyncBackend.connect_tcp
    calls = {"n": 0}

    def slow_first(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.8)  # a cold DNS lookup or a SYN retransmit
        return real(self, *a, **k)

    monkeypatch.setattr(backend.SyncBackend, "connect_tcp", slow_first)
    try:
        log = FetchLog(tmp_path / "fetch_log.jsonl")
        client = PoliteClient("citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)", log)
        client.get(f"http://127.0.0.1:{srv.server_address[1]}/page")
    finally:
        srv.shutdown()
        srv.server_close()
    assert len(seen) == 2 and seen[1] - seen[0] >= 0.98, seen
    assert audit(log) == []


def test_a_request_past_its_deadline_is_never_sent_late(tmp_path, monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpcore._backends.sync as backend

    from citewatch.fetch import FetchLog, PoliteClient

    seen: list[str] = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            seen.append(self.path)
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = backend.SyncBackend.connect_tcp

    def stall(self, *a, **k):
        time.sleep(1.8)  # longer than the 0.2 s timeout plus its 1 s grace
        return real(self, *a, **k)

    monkeypatch.setattr(backend.SyncBackend, "connect_tcp", stall)
    try:
        client = PoliteClient(
            "citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)",
            FetchLog(tmp_path / "fetch_log.jsonl"),
            timeout=0.2,
        )
        assert client._fetch_robots(f"http://127.0.0.1:{srv.server_address[1]}/robots.txt") == (
            None,
            None,
        )
        time.sleep(1.5)  # the abandoned worker connects now, and must not send
    finally:
        srv.shutdown()
        srv.server_close()
    assert seen == []


def test_a_block_seen_by_one_worker_stops_another_on_the_same_page(tmp_path):
    """v3 M2: the page history is checked after the wait, and one page goes at a time."""
    import threading

    def slow_403(request):
        time.sleep(0.2)
        return httpx.Response(403)

    web = FakeWeb(
        {
            "https://h.example/dir/": slow_403,
            "https://a.example/r": httpx.Response(
                301, headers={"location": "https://h.example/dir"}
            ),
        }
    )
    client, log, _ = make(tmp_path, web)
    t1 = threading.Thread(target=client.get, args=("https://h.example/dir/",))
    t1.start()
    time.sleep(0.05)
    client.get("https://a.example/r")
    t1.join()
    assert [u for u in web.urls() if u.startswith("https://h.example/dir")] == [
        "https://h.example/dir/"
    ]
    assert audit(log) == []


def test_escaped_markup_in_robots_lines_is_never_stored(tmp_path):
    body = (
        b"User-agent: *\nDisallow: /&lt;html lang=en&gt;\n"
        b'Disallow: /search?q=&lt;body onload\nAllow: /"body": x\n'
    )
    store = RawStore(tmp_path)
    web = FakeWeb({"https://a.example/robots.txt": httpx.Response(200, content=body)})
    client, _log, _ = make(tmp_path, web, store=store)
    client.get("https://a.example/p")
    files = list((tmp_path / "data" / "raw").rglob("*.gz"))
    assert files and all(storage_audit.file_problems(f, tmp_path) == [] for f in files)


def test_a_malformed_redirect_target_is_a_stored_error(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/p": httpx.Response(
                302, headers={"location": "https://a.example:99999/x"}
            )
        }
    )
    store = RawStore(tmp_path)
    client, _log, _ = make(tmp_path, web, store=store)
    res = fetch_pages(["https://a.example/p"], client=client, store=store)
    from citewatch.fetch import fetch_key

    assert (
        res.errors == []
        and store.get("fetch", fetch_key("https://a.example/p"))["outcome"] == "fetch_error"
    )


def test_the_wall_clock_wait_applies_after_a_later_pause():
    from citewatch.fetch import HostLimiter

    from .web import BASE

    clock = VClock()
    n = {"i": 0}

    def wall():
        n["i"] += 1
        extra = 0.1 if n["i"] == 2 else 0.0  # pause on the second grant's read
        return BASE + dt.timedelta(seconds=clock.now() + extra)

    lim = HostLimiter(clock=clock.now, sleep=clock.sleep, wall=wall)
    ats = []
    for _ in range(3):
        with lim.request("a.example") as at:
            ats.append(at)
    assert all((b - a).total_seconds() >= 1.0 for a, b in itertools.pairwise(ats))


def test_the_body_stream_stops_at_the_cap(tmp_path):
    pulled = {"n": 0}

    class Counting(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(1000):
                pulled["n"] += 4096
                yield b"x" * 4096

    web = FakeWeb(
        {"https://a.example/big": lambda r: httpx.Response(200, headers=HTML, stream=Counting())}
    )
    client, _log, _ = make(tmp_path, web, max_page_bytes=10_000)
    assert client.get("https://a.example/big").outcome == "too_large"
    assert pulled["n"] <= 10_000 + 2 * 4096


def test_seeding_uses_the_logged_time():
    from citewatch.fetch import HostLimiter

    from .web import BASE

    clock = VClock()
    lim = HostLimiter(clock=clock.now, sleep=clock.sleep, wall=clock.wall)
    lim.seed("a.example", BASE - dt.timedelta(seconds=0.5))  # 0.5 s before "now"
    with lim.request("a.example"):
        pass
    assert 0.5 <= clock.now() <= 0.6
    lim2 = HostLimiter(clock=clock.now, sleep=clock.sleep, wall=clock.wall)
    before = clock.now()
    lim2.seed("b.example", BASE - dt.timedelta(hours=1))
    with lim2.request("b.example"):
        pass
    assert clock.now() == before


def test_a_block_on_one_spelling_of_a_host_covers_the_other():
    h = PageHistory()
    h.seed(
        {
            "url": "https://bücher.example/p",
            "status": 403,
            "outcome": "blocked",
            "at": "2026-11-15T12:00:00Z",
        }
    )
    assert h.may_request("https://xn--bcher-kva.example/p") == "blocked earlier"


# --- pass 4 -------------------------------------------------------------------------------


def test_server_text_never_carries_markup_into_the_store_or_log(tmp_path):
    """v4 M1: redirect targets, header values and robots lines are encoded."""
    store = RawStore(tmp_path)
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /'html': x\n"
            ),
            "https://a.example/r": httpx.Response(302, headers={"location": "/<body class=x>"}),
            "https://a.example/e": httpx.Response(
                200,
                headers={**HTML, "etag": '"<html lang=en>"', "last-modified": "&lt;html>"},
                content=PAGE,
            ),
        }
    )
    client, log, _ = make(tmp_path, web, store=store)
    fetch_pages(["https://a.example/r", "https://a.example/e"], client=client, store=store)
    files = [*list((tmp_path / "data" / "raw").rglob("*.gz")), log.path]
    assert all(storage_audit.file_problems(f, tmp_path) == [] for f in files)
    assert audit(log) == []


def test_a_malformed_location_is_one_request_and_keeps_its_status(tmp_path):
    """v4 M2: never retried as a transport error."""
    store = RawStore(tmp_path)
    web = FakeWeb(
        {"https://a.example/p": httpx.Response(302, headers={"location": "http://[::1/x"})}
    )
    client, log, _ = make(tmp_path, web, store=store)
    fetch_pages(["https://a.example/p"], client=client, store=store)
    from citewatch.fetch import fetch_key

    rec = store.get("fetch", fetch_key("https://a.example/p"))
    assert web.urls().count("https://a.example/p") == 1
    assert rec["outcome"] == "fetch_error" and rec["status"] == 302
    assert audit(log) == []


def test_two_workers_on_one_host_wait_for_each_others_real_send(tmp_path, monkeypatch):
    """v4 M3: the per-host lock keeps wire gaps when two threads share a host."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpcore._backends.sync as backend

    from citewatch.fetch import FetchLog, PoliteClient

    seen: list[float] = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path != "/robots.txt":
                seen.append(time.monotonic())
                if len(seen) == 1:
                    time.sleep(0.5)  # still answering when the second grant comes due
            self.send_response(404 if self.path == "/robots.txt" else 200)
            body = b"" if self.path == "/robots.txt" else PAGE
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = backend.SyncBackend.connect_tcp
    lock = threading.Lock()
    n = {"i": 0}

    def slow_some(self, *a, **k):
        with lock:
            n["i"] += 1
            i = n["i"]
        if i == 2:
            time.sleep(0.8)  # the first page's connection is slow
        return real(self, *a, **k)

    monkeypatch.setattr(backend.SyncBackend, "connect_tcp", slow_some)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        client = PoliteClient(
            "citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)",
            FetchLog(tmp_path / "fetch_log.jsonl"),
        )
        client.robots.allows(base + "/x")  # robots first, so both pages race for the host
        ts = [threading.Thread(target=client.get, args=(f"{base}/p{i}",)) for i in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        srv.shutdown()
        srv.server_close()
    assert len(seen) == 2 and seen[1] - seen[0] >= 0.98, seen


def test_a_wall_clock_step_back_still_spaces_logged_times():
    """v4 low: the wall-clock wait is exercised on a granting read."""
    from citewatch.fetch import HostLimiter

    from .web import BASE

    clock = VClock()
    n = {"grants": 0}

    def wall():
        back = 0.5 if n["grants"] >= 1 else 0.0  # NTP stepped the clock back after grant 1
        return BASE + dt.timedelta(seconds=clock.now() - back)

    lim = HostLimiter(clock=clock.now, sleep=clock.sleep, wall=wall)
    ats = []
    for _ in range(3):
        with lim.request("a.example") as at:
            ats.append(at)
            n["grants"] += 1
    assert all((b - a).total_seconds() >= 1.0 for a, b in itertools.pairwise(ats))


# --- pass 5 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "routes",
    [
        {
            "https://a.example/p": httpx.Response(
                200, headers={**HTML, "etag": "\\u003chtml x"}, content=PAGE
            )
        },
        {"https://a.example/p": httpx.Response(302, headers={"location": "/\\u003chtml x"})},
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /\\u003chtml x\n"
            )
        },
        {"https://a.example/p": httpx.Response(302, headers={"location": "http://a&b.example/p"})},
        {
            "https://a.example/p": httpx.Response(
                302, headers={"location": "http://a<html>.example/p"}
            )
        },
    ],
)
def test_escapes_and_odd_hosts_never_reach_the_store_or_break_the_audit(tmp_path, routes):
    """v5 M1, M2."""
    store = RawStore(tmp_path)
    web = FakeWeb(routes)
    client, log, _ = make(tmp_path, web, store=store)
    fetch_pages(["https://a.example/p"], client=client, store=store)
    files = [*list((tmp_path / "data" / "raw").rglob("*.gz")), log.path]
    assert all(storage_audit.file_problems(f, tmp_path) == [] for f in files)
    assert audit(log) == []
    assert all(r.url.host == "a.example" for r in web.requests)  # never an odd host


def test_a_url_with_an_odd_host_is_never_requested(tmp_path):
    web = FakeWeb()
    client, _log, _ = make(tmp_path, web)
    assert client.get("http://a&b.example/p").detail == "not a plain host name"
    assert web.requests == []
    from citewatch.fetch.keys import plain_host

    assert plain_host("https://www.nhs.uk/x") and plain_host("https://bücher.example/")
    assert plain_host("http://[::1]:8080/x") and not plain_host("http://a'b.example/")


def test_an_idle_wall_clock_step_back_still_spaces_logged_times():
    """v5 M3: the step back happens while the host is idle and monotonic time is past due."""
    from citewatch.fetch import HostLimiter

    from .web import BASE

    clock = VClock()
    back = {"s": 0.0}
    lim = HostLimiter(
        clock=clock.now,
        sleep=clock.sleep,
        wall=lambda: BASE + dt.timedelta(seconds=clock.now() - back["s"]),
    )
    ats = []
    with lim.request("a.example") as at:
        ats.append(at)
    clock.sleep(1.1)  # idle: the next monotonic grant is already due
    back["s"] = 0.5  # NTP steps the wall clock back
    with lim.request("a.example") as at:
        ats.append(at)
    assert (ats[1] - ats[0]).total_seconds() >= 1.0


def test_a_redirect_without_location_is_an_error_not_a_new_outcome(tmp_path):
    store = RawStore(tmp_path)
    web = FakeWeb({"https://a.example/p": httpx.Response(302)})
    client, _log, _ = make(tmp_path, web, store=store)
    fetch_pages(["https://a.example/p"], client=client, store=store)
    from citewatch.fetch import fetch_key

    rec = store.get("fetch", fetch_key("https://a.example/p"))
    assert rec["outcome"] == "fetch_error" and rec["status"] == 302


# --- pass 6 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        "http://x<body>.example/robots.txt",
        "http://b&c.example/robots.txt",
        "http://u:pw@b.example/robots.txt",
    ],
)
def test_robots_redirects_get_the_page_redirect_checks(tmp_path, target):
    """v6 M1, L1: no odd host or credentials on the robots path either."""
    web = FakeWeb(
        {"https://a.example/robots.txt": httpx.Response(301, headers={"location": target})}
    )
    client, log, _ = make(tmp_path, web)
    assert client.get("https://a.example/p").outcome == "robots_disallowed"
    assert [str(r.url) for r in web.requests] == ["https://a.example/robots.txt"]
    assert all("authorization" not in r.headers for r in web.requests)
    assert audit(log) == [] and storage_audit.file_problems(log.path, tmp_path) == []


@pytest.mark.parametrize("host", ["straße.example", "ς.example", "a‍b.example"])
def test_hosts_whose_idna_forms_disagree_are_never_requested(tmp_path, host):
    """v6 M2: robots would be checked on one host and the page sent to another."""
    web = FakeWeb(
        {
            "https://a.example/p": httpx.Response(
                301, headers=[(b"location", f"http://{host}/x".encode())]
            )
        }
    )
    client, _log, _ = make(tmp_path, web)
    client.get("https://a.example/p")
    assert all(r.url.host == "a.example" for r in web.requests)
    from citewatch.fetch.keys import plain_host

    assert plain_host("https://bücher.example/") and plain_host("http://my_host.example/")


@pytest.mark.parametrize("charset", ["idna", "undefined", "no-such-charset"])
def test_an_odd_charset_still_stores_the_page_once(tmp_path, charset):
    """v6 M3: the page keeps its outcome and is never fetched again."""
    from citewatch.fetch import fetch_key

    store = RawStore(tmp_path)
    web = FakeWeb(
        {
            "https://a.example/p": httpx.Response(
                200, headers={"content-type": f"text/html; charset={charset}"}, content=PAGE
            )
        }
    )
    client, _log, _ = make(tmp_path, web, store=store)
    res = fetch_pages(
        ["https://a.example/p"], client=client, store=store, analyse=lambda p: {"n": len(p.html)}
    )
    assert res.errors == [] and store.has("fetch", fetch_key("https://a.example/p"))
    again = fetch_pages(["https://a.example/p"], client=client, store=store)
    assert again.cached == 1 and web.urls().count("https://a.example/p") == 1


def test_a_worker_failing_at_its_send_instant_never_loses_the_outcome(tmp_path, monkeypatch):
    """v6 L2: the RuntimeError from an abandoned send is a fetch_error, not a crash."""
    from citewatch.fetch import PoliteClient

    def boom(self, *a, **k):
        raise RuntimeError("request abandoned before it was sent")

    client, log, _ = make(tmp_path, FakeWeb())
    client.robots.allows("https://a.example/x")
    monkeypatch.setattr(PoliteClient, "_send", boom)
    r = client.get("https://a.example/p")
    assert r.outcome == "fetch_error" and audit(log) == []


def test_robots_redirect_loops_stay_within_the_page_budget(tmp_path):
    h = PageHistory()
    for _ in range(2):
        h.seed(
            {
                "url": "https://a.example/robots.txt",
                "status": 503,
                "outcome": "fetch_error",
                "at": "2026-11-15T11:00:00Z",
            }
        )
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                301, headers={"location": "http://a.example/robots.txt"}
            )
        }
    )
    client, _log, _ = make(tmp_path, web, history=h)
    assert client.get("https://a.example/p").outcome == "robots_disallowed"
    assert web.urls().count("https://a.example/robots.txt") == 1


# --- pass 7 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        b"User-agent *\nDisallow: /\n",
        b"User-agent: *\nDisallow /\n",
        b"User agent: citewatch\nDisallow: /\n",
        b"Useragent: *\nDisallow: /\n",
        b"User-agent: *\nDissallow: /\n",
        b"User-agent: *\n" + b"Allow: /a\n" * 5100 + b"Disallow: /\n",
    ],
)
def test_the_fetcher_applies_exactly_protegos_verdict(tmp_path, body):
    """v7 H1: no line protego reads is dropped before it reaches protego, stored or not."""
    from protego import Protego

    url = "https://a.example/page"
    assert Protego.parse(body.decode()).can_fetch(url, "citewatch") is False
    store = RawStore(tmp_path)
    web = FakeWeb({"https://a.example/robots.txt": httpx.Response(200, content=body)})
    client, log, _ = make(tmp_path, web, store=store)
    assert client.get(url).outcome == "robots_disallowed"
    later, _l, _ = make(tmp_path / "r2", FakeWeb(), store=store)  # the stored answer, re-read
    assert later.get(url).outcome == "robots_disallowed"
    assert "https://a.example/page" not in web.urls() and audit(log) == []


def test_an_unexpected_robots_failure_disallows():
    """v7 L2."""
    from citewatch.fetch import RobotsCache

    def boom(url):
        raise KeyError("bug")

    assert RobotsCache(boom).allows("https://a.example/p") is False


def test_refusal_rows_use_the_limiter_clock(tmp_path):
    """v7 L1: a request after a refusal would sort after it in the audit."""
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /no\n"
            )
        }
    )
    client, log, _clock = make(tmp_path, web)
    client.get("https://a.example/yes")
    client.get("https://a.example/no")
    refused = next(r for r in log.rows() if r["outcome"] == "robots_disallowed")
    assert refused["at"].startswith("2026-11-15T12:00")  # the virtual wall clock, not now()


# --- pass 8 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "routes"),
    [
        ("https://a.example/public/../private", {}),
        ("https://a.example/public/%2e%2e/private", {}),
        ("https://a.example/./private", {}),
        (
            "https://a.example/r",
            {
                "https://a.example/r": httpx.Response(
                    301, headers={"location": "https://a.example/x/../private"}
                )
            },
        ),
    ],
)
def test_dot_segments_never_get_past_robots(tmp_path, start, routes):
    """v8 H1: robots is checked on the path the server will receive."""
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /private\n"
            ),
            **routes,
        }
    )
    client, log, _ = make(tmp_path, web)
    assert client.get(start).outcome == "robots_disallowed"
    assert not any(r.url.path.startswith("/private") for r in web.requests)
    assert audit(log) == []


def test_a_block_is_remembered_through_dot_segments(tmp_path):
    web = FakeWeb({"https://a.example/private": httpx.Response(403)})
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/private").outcome == "blocked"
    assert client.get("https://a.example/x/../private").outcome == "blocked"
    assert [r.url.path for r in web.requests].count("/private") == 1


def test_the_audit_resolves_dot_segments():
    import fetch_audit

    assert (
        fetch_audit.norm_url("https://a.example/public/../private") == "https://a.example/private"
    )
    assert fetch_audit.norm_url("https://a.example/a/%2e%2e/b") == "https://a.example/b"
    import json

    base = {"host": "a.example", "attempt": 1, "user_agent": "citewatch/0.1"}
    rows = [
        json.dumps(
            {
                **base,
                "url": "https://a.example/private",
                "at": "2026-11-15T12:00:00+00:00",
                "status": None,
                "bytes": None,
                "robots": "disallowed",
                "outcome": "robots_disallowed",
            }
        ),
        json.dumps(
            {
                **base,
                "url": "https://a.example/x/../private",
                "at": "2026-11-15T12:00:05+00:00",
                "status": 200,
                "bytes": 10,
                "robots": "allowed",
                "outcome": "ok",
            }
        ),
    ]
    assert any("robots refused" in p for p in fetch_audit.audit(rows))


def test_robots_rules_on_the_query_are_honoured(tmp_path):
    """v8 M1: fresh and from the store."""
    store = RawStore(tmp_path)
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /*?s=\n"
            )
        }
    )
    client, _log, _ = make(tmp_path, web, store=store)
    assert client.get("https://a.example/p?s=1").outcome == "robots_disallowed"
    assert client.get("https://a.example/p?t=1").outcome == "ok"
    later, _l, _ = make(tmp_path / "r2", FakeWeb(), store=store)
    assert later.get("https://a.example/q?s=2").outcome == "robots_disallowed"


def test_a_cut_robots_file_never_keeps_a_half_line(tmp_path):
    """v8 L1: a truncated `Allow: /private-ok` must not become `Allow: /priv`."""
    from citewatch.fetch.robots import MAX_ROBOTS_BYTES

    head = b"User-agent: *\nDisallow: /pri\n"
    pad = b"# " + b"x" * 60 + b"\n"
    body = head + pad * ((MAX_ROBOTS_BYTES - len(head) - 10) // len(pad))
    body += b"Allow: /private-ok\n"
    web = FakeWeb({"https://a.example/robots.txt": httpx.Response(200, content=body)})
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/private").outcome == "robots_disallowed"


def test_answers_stored_under_an_older_robots_version_are_read_again(tmp_path):
    """v8 L2: a robots-2 answer (allow-all here) is never used by robots-3."""
    from citewatch.fetch.robots import ROBOTS_CODE_VERSION
    from citewatch.store import stage_key

    assert ROBOTS_CODE_VERSION == "robots-3"
    store = RawStore(tmp_path)
    old = stage_key("robots", "robots-2", {"origin": "https://a.example"}, "")
    store.put("robots", old, {"origin": "https://a.example", "status": 404, "directives": []})
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /\n"
            )
        }
    )
    client, _log, _ = make(tmp_path, web, store=store)
    assert client.get("https://a.example/p").outcome == "robots_disallowed"
    assert web.urls() == ["https://a.example/robots.txt"]


# --- pass 9: each guard pinned by a test that kills its mutant -----------------------------


def test_a_robots_file_cut_inside_an_allow_line_drops_that_line(tmp_path):
    """v9 M1: the cut really lands inside `Allow: /private-ok`."""
    from citewatch.fetch.robots import MAX_ROBOTS_BYTES

    head = b"User-agent: *\nDisallow: /pri\n"
    fill = MAX_ROBOTS_BYTES - len(head) - len(b"Allow: /priv")  # bytes of comment lines
    lines = []
    while fill > 0:
        n = min(64, fill) if fill - min(64, fill) != 1 else 32  # never leave a 1-byte line
        lines.append(b"#" * (n - 1) + b"\n")
        fill -= n
    body = head + b"".join(lines) + b"Allow: /private-ok\n" + b"#more\n" * 10
    assert body[:MAX_ROBOTS_BYTES].endswith(b"\nAllow: /priv")
    web = FakeWeb({"https://a.example/robots.txt": httpx.Response(200, content=body)})
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/private").outcome == "robots_disallowed"


def test_upper_case_encoded_dots_in_a_redirect_are_resolved(tmp_path):
    """v9 M2 #2."""
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /private\n"
            ),
            "https://a.example/r": httpx.Response(301, headers={"location": "/x/%2E%2E/private"}),
        }
    )
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/r").outcome == "robots_disallowed"
    assert not any(r.url.path.startswith("/private") for r in web.requests)


def test_the_page_key_resolves_dots_itself(tmp_path):
    """v9 M2 #6: a target `wire_url` leaves alone (`%2F..`) still maps to the blocked page."""
    web = FakeWeb(
        {
            "https://a.example/a": httpx.Response(403),
            "https://a.example/r": httpx.Response(301, headers={"location": "/a/b%2F.."}),
        }
    )
    client, log, _ = make(tmp_path, web)
    assert client.get("https://a.example/a").outcome == "blocked"
    client.get("https://a.example/r")
    assert audit(log) == []


def test_a_robots_refusal_is_remembered_for_the_same_page(tmp_path):
    """v9 M2 #17: `/x/` refused, then `/x` (same page identity) is never requested."""
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /x/\n"
            )
        }
    )
    client, log, _ = make(tmp_path, web)
    assert client.get("https://a.example/x/").outcome == "robots_disallowed"
    assert client.get("https://a.example/x").outcome == "robots_disallowed"
    assert "https://a.example/x" not in web.urls() and audit(log) == []


def test_logged_urls_are_cleaned(tmp_path):
    """v9 M2 #23: quotes reach the log through a redirect target httpx does not encode."""
    web = FakeWeb({"https://a.example/r": httpx.Response(301, headers={"location": "/'body':x"})})
    client, log, _ = make(tmp_path, web)
    client.get("https://a.example/r")
    assert storage_audit.file_problems(log.path, tmp_path) == []


def test_merged_slashes_cannot_get_past_robots(tmp_path):
    """v9 L1: Apache serves `//private/` as `/private/`."""
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /private\n"
            )
        }
    )
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example//private/").outcome == "robots_disallowed"
    assert client.get("https://a.example/public//page").outcome == "ok"
