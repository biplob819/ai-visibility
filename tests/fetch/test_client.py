"""FET-02, FET-03, FET-04, FET-07, FET-08: rate, user agent, retries, gating and the log."""

import datetime as dt
import itertools
import threading

import httpx
import pytest

from citewatch.fetch import HostLimiter, PageHistory, page_key
from citewatch.fetch.log import FIELDS

from .web import HTML, PAGE, UA, FakeWeb, VClock, audit, make

pytestmark = pytest.mark.polite


def page(status=200, body=PAGE, headers=None):
    return httpx.Response(status, headers=headers or HTML, content=body)


def test_one_host_is_asked_at_most_once_a_second_even_under_concurrency():
    clock = VClock()
    lim = HostLimiter(clock=clock.now, sleep=clock.sleep, wall=clock.wall)
    grants: list[dt.datetime] = []
    lock = threading.Lock()

    def worker():
        for _ in range(5):
            with lim.request("A.Example.") as at, lock:
                grants.append(at)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    grants.sort()
    gaps = [(b - a).total_seconds() for a, b in itertools.pairwise(grants)]
    assert len(grants) == 40 and min(gaps) >= 1.0


def test_robots_hops_and_pages_on_one_host_share_the_rate(tmp_path):
    web = FakeWeb({"https://a.example/r": httpx.Response(301, headers={"location": "/p"})})
    client, log, _ = make(tmp_path, web)
    client.get("https://a.example/r")
    client.get("https://a.example/q")
    ats = [dt.datetime.fromisoformat(r["at"]) for r in log.rows()]
    assert len(ats) == 4  # robots, the redirect, its target, the second page
    assert all((b - a).total_seconds() >= 1.0 for a, b in itertools.pairwise(ats))
    assert audit(log) == []


def test_no_more_than_eight_requests_are_in_flight(tmp_path):
    from citewatch.fetch import fetch_pages
    from citewatch.store import RawStore

    web = FakeWeb(delay=0.02)
    client, log, _ = make(tmp_path, web)
    urls = [f"https://h{i}.example/p" for i in range(24)]
    res = fetch_pages(urls, client=client, store=RawStore(tmp_path))
    assert res.fetched == 24 and web.max_live <= 8 and client.limiter.max_live <= 8
    assert web.max_live >= 2  # the limit is used, not serialised to one
    assert audit(log) == []


def test_every_request_carries_the_study_user_agent(tmp_path):
    web = FakeWeb(
        {"https://a.example/x": httpx.Response(302, headers={"location": "https://b.example/"})}
    )
    client, log, _ = make(tmp_path, web)
    client.get("https://a.example/x")
    assert {r.headers["user-agent"] for r in web.requests} == {UA}
    assert {r["user_agent"] for r in log.rows()} == {UA}
    assert all("cookie" not in r.headers for r in web.requests)
    with pytest.raises(ValueError, match="citewatch/"):
        make(tmp_path, web)[0].__class__("Mozilla/5.0", log)


@pytest.mark.parametrize(
    ("replies", "outcome", "n"),
    [
        ([page(503), page(503), page()], "ok", 3),
        ([page(503)] * 5, "fetch_error", 3),
        ([httpx.ConnectError("x"), page()], "ok", 2),
        ([httpx.ReadTimeout("x")] * 5, "fetch_error", 3),
        ([page(500), page(502), page(504), page()], "fetch_error", 3),
        ([page(403), page()], "blocked", 1),
        ([page(401), page()], "blocked", 1),
        ([page(451), page()], "blocked", 1),
        ([page(404), page()], "fetch_error", 1),
    ],
)
def test_retries_follow_the_rules(tmp_path, replies, outcome, n):
    web = FakeWeb({"https://a.example/p": replies})
    client, log, _ = make(tmp_path, web)
    assert client.get("https://a.example/p").outcome == outcome
    assert web.urls().count("https://a.example/p") == n
    attempts = [r["attempt"] for r in log.rows() if r["url"] == "https://a.example/p"]
    assert attempts == list(range(1, n + 1))
    assert audit(log) == []


def test_retry_after_is_honoured_up_to_60_seconds(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/p": [page(429, headers={"retry-after": "30"}), page()],
            "https://a.example/q": [page(429, headers={"retry-after": "120"}), page()],
        }
    )
    client, log, clock = make(tmp_path, web)
    before = clock.now()
    assert client.get("https://a.example/p").outcome == "ok"
    assert clock.now() - before >= 30
    r = client.get("https://a.example/q")
    assert r.status == 429 and web.urls().count("https://a.example/q") == 1
    assert audit(log) == []


def test_the_timeout_is_ten_seconds_and_a_slow_body_is_cut(tmp_path):
    import itertools

    ticks = itertools.count(step=4)
    web = FakeWeb()
    client, log, _ = make(tmp_path, web, clock=lambda: next(ticks))
    assert client.timeout == 10.0 and client._http.timeout.read == 10.0
    big = b"<html>" + b"x" * 300_000

    def stream(request):
        return httpx.Response(200, headers=HTML, stream=httpx.ByteStream(big))

    web.add("https://a.example/slow", stream)
    r = client.get("https://a.example/slow")
    assert r.outcome in {"ok", "fetch_error"} and audit(log) == []


def test_history_from_earlier_runs_limits_requests(tmp_path):
    url = "https://a.example/p"
    earlier = [
        {"url": url, "status": 503, "outcome": "fetch_error"},
        {"url": "http://a.example/p/", "status": 503, "outcome": "fetch_error"},  # same page
        {"url": "https://a.example/blocked", "status": 403, "outcome": "blocked"},
        {"url": "https://a.example/refused", "status": None, "outcome": "robots_disallowed"},
    ]
    history = PageHistory()
    for row in earlier:
        history.seed(row)
    web = FakeWeb({url: [page(503)] * 5})
    client, _log, _ = make(tmp_path, web, history=history)
    assert client.get(url).outcome == "fetch_error"
    assert web.urls().count(url) == 1  # 2 earlier + 1 now = the 3-request budget
    assert client.get("https://a.example/blocked").outcome == "blocked"
    assert client.get("https://a.example/refused").outcome == "robots_disallowed"
    assert "https://a.example/blocked" not in web.urls()
    assert "https://a.example/refused" not in web.urls()


def test_a_page_reached_twice_in_one_run_is_requested_once(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/one": httpx.Response(301, headers={"location": "/shared"}),
            "https://a.example/two": httpx.Response(301, headers={"location": "/shared"}),
        }
    )
    client, log, _ = make(tmp_path, web)
    assert client.get("https://a.example/one").outcome == "ok"
    assert client.get("https://a.example/two").outcome == "ok"
    assert web.urls().count("https://a.example/shared") == 1
    assert audit(log) == []


def test_redirect_limits(tmp_path):
    loop = {
        f"https://a.example/{i}": httpx.Response(302, headers={"location": f"/{i + 1}"})
        for i in range(10)
    }
    loop["https://a.example/m"] = httpx.Response(302, headers={"location": "mailto:x@y.z"})
    web = FakeWeb(loop)
    client, log, _ = make(tmp_path, web)
    assert client.get("https://a.example/0").detail == "too many redirects"
    assert len([u for u in web.urls() if not u.endswith("robots.txt")]) == 6
    assert client.get("https://a.example/m").outcome == "fetch_error"
    assert audit(log) == []


@pytest.mark.parametrize(
    "body",
    [
        b'<html><form><input name="u"><input type="password" name="p"></form></html>',
        b"<html><INPUT TYPE=password></html>",
        b'<html><script type="application/ld+json">{"isAccessibleForFree": false}</script></html>',
        b'<html><script type="application/ld+json">{"isAccessibleForFree":"False"}</script></html>',
        b'<html><meta itemprop="isAccessibleForFree" content="false"></html>',
    ],
)
def test_login_walls_and_paywalls_are_gated_without_a_workaround(tmp_path, body):
    web = FakeWeb({"https://a.example/p": page(body=body)})
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/p").outcome == "gated"
    assert web.urls().count("https://a.example/p") == 1


def test_a_free_page_mentioning_passwords_is_not_gated(tmp_path):
    body = (
        b"<html><p>Never share your password.</p>"
        b'<script>{"isAccessibleForFree": true}</script></html>'
    )
    web = FakeWeb({"https://a.example/p": page(body=body)})
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/p").outcome == "ok"


def test_the_log_has_every_field_and_passes_the_audit(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /no\n"
            )
        }
    )
    client, log, _ = make(tmp_path, web)
    client.get("https://a.example/yes")
    client.get("https://a.example/no")
    rows = log.rows()
    assert all(set(r) == set(FIELDS) for r in rows)
    assert all(r["at"].endswith("Z") and r["host"] == "a.example" for r in rows)
    assert [r["outcome"] for r in rows] == ["ok", "ok", "robots_disallowed"]
    assert audit(log) == []


def test_page_identity_matches_the_audit():
    import fetch_audit

    urls = [
        "https://A.example/p/",
        "http://a.example/p",
        "https://a.example:443/p?b=2&a=1#frag",
        "https://a.example/%7Euser",
        "https://[::1]:8443/x/",
        "https://a.example./",
        "https://a.example",
    ]
    for u in urls:
        assert page_key(u) == fetch_audit.page_key(fetch_audit.norm_url(u)), u
