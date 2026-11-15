"""FET-01, FET-03: robots.txt per §7.2, parsed with protego."""

import httpx
import pytest

from citewatch.fetch import RobotsCache
from citewatch.fetch.robots import origin_of, rules_from
from citewatch.store import RawStore

from .web import HTML, PAGE, UA, FakeWeb, audit, make

pytestmark = pytest.mark.polite

LONGEST = b"User-agent: *\nAllow: /\nDisallow: /private\n"


def robots(body: bytes, status: int = 200) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": "text/plain"}, content=body)


def test_the_longest_match_disallows_what_urllib_would_allow(tmp_path):
    """H4: urllib's first-match reads `Allow: /` first and fetches /private; RFC 9309 does not."""
    import urllib.robotparser

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(LONGEST.decode().splitlines())
    assert rp.can_fetch("citewatch", "https://a.example/private/x")  # the bug we avoid
    web = FakeWeb({"https://a.example/robots.txt": robots(LONGEST)})
    client, log, _ = make(tmp_path, web)
    assert client.get("https://a.example/private/x").outcome == "robots_disallowed"
    assert client.get("https://a.example/public").outcome == "ok"
    assert "https://a.example/private/x" not in web.urls()
    rows = log.rows()
    refused = [r for r in rows if r["url"] == "https://a.example/private/x"]
    assert refused == [r for r in refused if r["status"] is None and r["robots"] == "disallowed"]
    assert audit(log) == []


@pytest.mark.parametrize(
    ("reply", "allowed"),
    [
        (robots(b"", 404), True),
        (robots(b"", 410), True),
        (robots(b"", 418), True),
        (robots(b"", 401), False),
        (robots(b"", 403), False),
        (robots(b"", 500), False),
        (robots(b"", 503), False),
        (httpx.ReadTimeout("slow"), False),
        (httpx.ConnectError("down"), False),
    ],
)
def test_robots_status_rules(tmp_path, reply, allowed):
    web = FakeWeb({"https://a.example/robots.txt": reply})
    client, log, _ = make(tmp_path, web)
    outs = [client.get(f"https://a.example/p{i}").outcome for i in range(3)]
    assert outs == (["ok"] * 3 if allowed else ["robots_disallowed"] * 3)
    pages = [u for u in web.urls() if not u.endswith("/robots.txt")]
    assert len(pages) == (3 if allowed else 0)  # a refused host gets no page request at all
    assert web.urls().count("https://a.example/robots.txt") == 1  # no retry for robots
    assert audit(log) == []


def test_robots_is_fetched_once_per_origin_and_kept_for_the_study(tmp_path):
    store = RawStore(tmp_path)
    web = FakeWeb({"https://a.example/robots.txt": robots(b"User-agent: *\nDisallow: /x\n")})
    client, log, _ = make(tmp_path, web, store=store)
    for i in range(4):
        client.get(f"https://a.example/p{i}")
    client.get("http://a.example/q")  # another origin: its own robots.txt
    assert web.urls().count("https://a.example/robots.txt") == 1
    assert web.urls().count("http://a.example/robots.txt") == 1
    web2 = FakeWeb()
    later, log2, _ = make(tmp_path / "run2", web2, store=store)  # a later run, same study
    assert later.get("https://a.example/x/1").outcome == "robots_disallowed"
    assert later.get("https://a.example/p9").outcome == "ok"
    assert "https://a.example/robots.txt" not in web2.urls()
    assert audit(log) == [] and audit(log2) == []


def test_a_redirect_to_a_new_host_checks_that_hosts_robots(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/x": httpx.Response(301, headers={"location": "https://b.example/y"}),
            "https://b.example/robots.txt": robots(b"User-agent: *\nDisallow: /y\n"),
            "https://a.example/z": httpx.Response(
                302, headers={"location": "https://b.example/ok"}
            ),
        }
    )
    client, log, _ = make(tmp_path, web)
    r = client.get("https://a.example/x")
    assert r.outcome == "robots_disallowed" and r.final_url == "https://b.example/y"
    assert "https://b.example/y" not in web.urls()
    ok = client.get("https://a.example/z")
    assert ok.outcome == "ok" and ok.final_url == "https://b.example/ok"
    assert ok.hops == ["https://b.example/ok"]
    assert audit(log) == []


def test_a_robots_redirect_away_from_robots_txt_disallows(tmp_path):
    web = FakeWeb(
        {"https://a.example/robots.txt": httpx.Response(302, headers={"location": "/login"})}
    )
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/p").outcome == "robots_disallowed"
    assert "https://a.example/login" not in web.urls()


def test_rules_match_the_citewatch_token_and_the_full_user_agent():
    r = rules_from(200, "User-agent: citewatch\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert not r.allows("https://a.example/page")
    other = rules_from(200, "User-agent: googlebot\nDisallow: /\n")
    assert other.allows("https://a.example/page")
    assert UA.startswith("citewatch/")


def test_origins_and_concurrent_askers_share_one_fetch():
    import threading

    calls = []

    def fetch(url):
        calls.append(url)
        return 200, "User-agent: *\nDisallow: /no\n"

    cache = RobotsCache(fetch)
    threads = [
        threading.Thread(target=cache.allows, args=(f"https://A.example:443/p{i}",))
        for i in range(16)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert calls == ["https://a.example/robots.txt"]
    assert origin_of("http://a.example:8080/x") == "http://a.example:8080"


def test_pages_that_are_not_html_robots_are_still_parsed(tmp_path):
    web = FakeWeb(
        {
            "https://a.example/robots.txt": httpx.Response(
                200, headers=HTML, content=b"User-agent: *\nDisallow: /\n"
            )
        }
    )
    client, _log, _ = make(tmp_path, web)
    assert client.get("https://a.example/p").outcome == "robots_disallowed"
    assert PAGE  # the default page is only served where robots allows
