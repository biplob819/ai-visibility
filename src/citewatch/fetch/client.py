"""The polite HTTP client (Tech Spec §7.2, FET-01..04).

`get` follows at most five redirects by hand: every hop is checked against its host's
robots.txt and waits for its host's rate grant, and every request is logged. Transport
errors, 5xx and 429 are retried at most twice (Retry-After honoured up to 60 s); 401, 403,
451 and robots refusals never are. No cookies are kept and nothing is worked around (B8).
"""

from __future__ import annotations

import datetime as dt
import email.utils
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .history import PageHistory
from .keys import host_of
from .log import FetchLog
from .rate import HostLimiter
from .robots import MAX_ROBOTS_BYTES, RobotsCache

TIMEOUT_S = 10.0
MAX_RETRIES = 2
MAX_REDIRECTS = 5
MAX_RETRY_AFTER_S = 60.0
MAX_PAGE_BYTES = 5 * 1024 * 1024
BLOCK_STATUSES = frozenset({401, 403, 451})
REDIRECTS = frozenset({301, 302, 303, 307, 308})
TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
KEEP_HEADERS = ("content-type", "content-length", "last-modified", "date", "etag", "age")

_PASSWORD = re.compile(rb"<input\b[^>]*\btype\s*=\s*[\"']?password", re.I)
_PAYWALL = re.compile(
    rb"[\"']isAccessibleForFree[\"']\s*:\s*(?:false|[\"']false[\"'])"
    rb"|itemprop\s*=\s*[\"']isAccessibleForFree[\"'][^>]*content\s*=\s*[\"']false",
    re.I,
)


@dataclass
class FetchResult:
    url: str
    final_url: str | None
    outcome: str  # ok, robots_disallowed, blocked, gated, not_html, too_large, fetch_error
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None  # in memory only; never stored
    fetched_at: dt.datetime | None = None
    hops: list[str] = field(default_factory=list)
    robots: str = "allowed"
    detail: str | None = None
    transient: bool = False  # a timeout or network error, worth another try


def is_gated(body: bytes) -> bool:
    return bool(_PASSWORD.search(body) or _PAYWALL.search(body))


def _retry_after(value: str | None, now: dt.datetime) -> float | None:
    if not value:
        return 0.0
    v = value.strip()
    if v.isdigit():
        return float(v)
    try:
        when = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return max(0.0, (when - now).total_seconds())


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        log: FetchLog,
        *,
        limiter: HostLimiter | None = None,
        history: PageHistory | None = None,
        transport: httpx.BaseTransport | None = None,
        store: Any = None,
        timeout: float = TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_page_bytes: int = MAX_PAGE_BYTES,
    ) -> None:
        if not user_agent.startswith("citewatch/"):
            raise ValueError("the user agent must start with citewatch/<version> (FET-03)")
        self.user_agent = user_agent
        self.log = log
        self.limiter = limiter or HostLimiter()
        self.history = history or PageHistory()
        self.robots = RobotsCache(self._fetch_robots, store)
        self._sleep, self._clock = sleep, clock
        self.timeout = timeout
        self.max_page_bytes = max_page_bytes
        self._http = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.1"},
            trust_env=False,
        )

    def close(self) -> None:
        self._http.close()

    # -- robots ---------------------------------------------------------------------------
    def _fetch_robots(self, robots_url: str) -> tuple[int | None, str | None]:
        """A robots.txt request, rate-limited and logged; redirects followed only to another
        robots.txt. No retries: 5xx or a timeout simply disallows."""
        url = robots_url
        for _ in range(MAX_REDIRECTS + 1):
            r = self._once(url, attempt=1, kind="robots", limit=MAX_ROBOTS_BYTES)
            if r.status in REDIRECTS and r.headers.get("location"):
                nxt = urljoin(url, r.headers["location"])
                if urlsplit(nxt).path != "/robots.txt":
                    return None, None
                url = nxt
                continue
            text = None if r.body is None else r.body.decode("utf-8", errors="replace")
            if r.outcome == "too_large" and r.body is not None:
                return r.status, text  # parse what fits, as RFC 9309 allows
            return r.status, text
        return None, None

    # -- one request ----------------------------------------------------------------------
    def _once(self, url: str, *, attempt: int, kind: str, limit: int) -> FetchResult:
        """One request: wait for the host's grant, send, read a capped body, log it."""
        res = FetchResult(url=url, final_url=url, outcome="fetch_error")
        nbytes: int | None = None
        with self.limiter.request(host_of(url)) as at:
            res.fetched_at = at
            start = self._clock()
            try:
                with self._http.stream("GET", url) as resp:
                    res.status = resp.status_code
                    res.headers = {
                        k: resp.headers[k]
                        for k in (*KEEP_HEADERS, "location", "retry-after")
                        if k in resp.headers
                    }
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    read = 200 <= resp.status_code < 300 and (
                        kind != "page" or ctype == "text/html"
                    )
                    if read:
                        buf = bytearray()
                        for chunk in resp.iter_bytes():
                            buf += chunk
                            if len(buf) > limit:
                                break
                            if self._clock() - start > self.timeout:
                                raise httpx.ReadTimeout("body took longer than the timeout")
                        nbytes = min(len(buf), limit + 1)
                        res.body = bytes(buf[:limit])
                        res.outcome = "too_large" if len(buf) > limit else "ok"
                    else:
                        nbytes = 0
                        res.outcome = self._status_outcome(resp.status_code, ctype, kind)
            except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError) as exc:
                res.status, res.outcome, res.detail = None, "fetch_error", type(exc).__name__
                res.transient = isinstance(exc, TRANSIENT)
                nbytes = None
            finally:
                self._http.cookies.clear()
            if kind == "page" and res.outcome == "ok" and res.body and is_gated(res.body):
                res.outcome = "gated"
            self.history.record(url, res.status)
            self.log.write(
                url=url,
                at=at,
                attempt=attempt,
                status=res.status,
                nbytes=nbytes,
                robots="allowed",
                outcome=res.outcome,
                user_agent=self.user_agent,
            )
        return res

    @staticmethod
    def _status_outcome(status: int, ctype: str, kind: str) -> str:
        if status in BLOCK_STATUSES:
            return "blocked"
        if status in REDIRECTS:
            return "redirect"
        if 200 <= status < 300 and kind == "page":
            return "not_html"
        return "fetch_error"

    def _with_retries(self, url: str, kind: str, limit: int) -> FetchResult:
        """One page's requests, serialised per page; a result from this run is reused."""
        entry = self.history.entry(url)
        with entry.lock:
            if entry.result is not None:
                return replace(entry.result, hops=[])
            r = self._attempts(url, kind, limit)
            if r.detail is None or r.status is not None:
                entry.result = r
            return replace(r, hops=[])

    def _attempts(self, url: str, kind: str, limit: int) -> FetchResult:
        attempt = 0
        while True:
            reason = self.history.may_request(url)
            if reason is not None:
                outcome = "blocked" if "blocked" in reason else "fetch_error"
                return FetchResult(url=url, final_url=url, outcome=outcome, detail=reason)
            attempt += 1
            r = self._once(url, attempt=attempt, kind=kind, limit=limit)
            retryable = r.transient or (
                r.status is not None and (r.status >= 500 or r.status == 429)
            )
            if not retryable or attempt > MAX_RETRIES:
                return r
            if r.status == 429:
                wait = _retry_after(r.headers.get("retry-after"), dt.datetime.now(dt.UTC))
                if wait is None or wait > MAX_RETRY_AFTER_S:
                    r.detail = "Retry-After too long or unreadable; not retried"
                    return r
                if wait > 0:
                    self._sleep(wait)

    # -- a page, with redirects -----------------------------------------------------------
    def get(self, url: str, kind: str = "page") -> FetchResult:
        """Fetch `url` politely; `kind` is "page" (HTML only, 5 MB) or "sitemap"."""
        limit = self.max_page_bytes
        current, hops = url, []
        for _ in range(MAX_REDIRECTS + 1):
            if self.history.entry(current).robots_refused or not self.robots.allows(current):
                self.history.refuse(current)
                self.log.write(
                    url=current,
                    at=dt.datetime.now(dt.UTC),
                    attempt=1,
                    status=None,
                    nbytes=None,
                    robots="disallowed",
                    outcome="robots_disallowed",
                    user_agent=self.user_agent,
                )
                return FetchResult(
                    url=url,
                    final_url=current,
                    outcome="robots_disallowed",
                    hops=hops,
                    robots="disallowed",
                )
            r = self._with_retries(current, kind, limit)
            if r.status in REDIRECTS and r.headers.get("location"):
                nxt = urljoin(current, r.headers["location"])
                if urlsplit(nxt).scheme not in ("http", "https"):
                    return FetchResult(
                        url,
                        current,
                        "fetch_error",
                        r.status,
                        hops=hops,
                        detail="redirect to a non-web scheme",
                    )
                hops.append(nxt)
                current = nxt
                continue
            r.url, r.final_url, r.hops = url, current, hops
            return r
        return FetchResult(url, current, "fetch_error", hops=hops, detail="too many redirects")
