"""The polite HTTP client (Tech Spec §7.2, FET-01..04).

`get` follows at most five redirects by hand: every hop is checked against its host's
robots.txt and waits for its host's rate grant, and every request is logged. Transport
errors, 5xx and 429 are retried at most twice (Retry-After honoured up to 60 s); 401, 403,
451 and robots refusals never are. No cookies are kept and nothing is worked around (B8).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import email.utils
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeout
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
    rb"|itemprop\s*=\s*[\"']isAccessibleForFree[\"'][^>]*content\s*=\s*[\"']false"
    rb"|content\s*=\s*[\"']false[\"'][^>]*itemprop\s*=\s*[\"']isAccessibleForFree",
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


_COMMENT = re.compile(rb"<!--.*?-->", re.S)


def is_gated(body: bytes) -> bool:
    visible = _COMMENT.sub(b"", body)  # a commented-out form is not a login wall
    return bool(_PASSWORD.search(visible) or _PAYWALL.search(visible))


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
        self._transport = transport
        self._timeout_cfg = httpx.Timeout(timeout)
        for host, at in self.history.last_at.items():
            self.limiter.seed(host, at)  # a resumed run never comes back too soon (v1 H1)

    def close(self) -> None:
        """Nothing is pooled: each request has its own client and thread."""

    # -- robots ---------------------------------------------------------------------------
    def _fetch_robots(self, robots_url: str) -> tuple[int | None, str | None]:
        """A robots.txt request, rate-limited, logged and within the page budget; redirects
        are followed only to another web robots.txt not seen yet. No retries: 5xx, a timeout
        or a loop simply disallows."""
        url, seen = robots_url, set()
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname or url in seen:
                return None, None  # file:, a missing host or a loop (v1 M3, M4)
            seen.add(url)
            if self.history.may_request(url) is not None:
                return None, None
            r = self._once(url, attempt=1, kind="robots", limit=MAX_ROBOTS_BYTES)
            if r.status in REDIRECTS and r.headers.get("location"):
                nxt = urljoin(url, r.headers["location"])
                if urlsplit(nxt).path != "/robots.txt":
                    return None, None
                url = nxt
                continue
            text = None if r.body is None else r.body.decode("utf-8", errors="replace")
            return r.status, text  # a too_large body is parsed as far as it goes (RFC 9309)
        return None, None

    # -- one request ----------------------------------------------------------------------
    def _send(self, url: str, kind: str, limit: int, holder: list[Any]) -> dict[str, Any]:
        """The HTTP exchange, on a fresh client per request (no cookies or connections are
        shared between requests, v1 M6). Runs on a worker so the caller can bound it."""
        out: dict[str, Any] = {"status": None, "headers": {}, "body": None, "nbytes": None}
        start = self._clock()
        with httpx.Client(
            transport=self._transport,
            timeout=self._timeout_cfg,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,*/*;q=0.1"},
            trust_env=False,
        ) as http:
            holder.append(http)
            with http.stream("GET", url) as resp:
                out["status"] = resp.status_code
                out["headers"] = {
                    k: resp.headers[k]
                    for k in (*KEEP_HEADERS, "location", "retry-after")
                    if k in resp.headers
                }
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                out["ctype"] = ctype
                if 200 <= resp.status_code < 300 and (kind != "page" or ctype == "text/html"):
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf += chunk
                        if len(buf) > limit:
                            break
                        if self._clock() - start > self.timeout:
                            raise httpx.ReadTimeout("body took longer than the timeout")
                    out["nbytes"] = min(len(buf), limit + 1)
                    out["body"] = bytes(buf[: limit + 1])
                else:
                    out["nbytes"] = 0
        return out

    def _once(self, url: str, *, attempt: int, kind: str, limit: int) -> FetchResult:
        """One request: wait for the host's grant, send with a hard deadline for the whole
        exchange (headers included, v1 M5), read a capped body, log it."""
        res = FetchResult(url=url, final_url=url, outcome="fetch_error")
        nbytes: int | None = None
        with self.limiter.request(host_of(url)) as at:
            res.fetched_at = at
            holder: list[Any] = []
            box: dict[str, Any] = {}

            def work() -> None:
                try:
                    box["out"] = self._send(url, kind, limit, holder)
                except BaseException as exc:
                    box["exc"] = exc

            # a fresh daemon thread per request, started right after the grant: a stuck
            # request (a DNS lookup has no timeout) never delays later ones, and `at` is the
            # real send time (v2 H-1)
            th = threading.Thread(target=work, daemon=True, name="citewatch-fetch")
            th.start()
            th.join(self.timeout + 1.0)
            try:
                if th.is_alive():
                    raise FutureTimeout
                if "exc" in box:
                    raise box["exc"]
                out = box["out"]
            except FutureTimeout:
                for http in holder:  # best effort: drop the stalled connection
                    with contextlib.suppress(Exception):
                        http.close()
                res.detail, res.transient = "timeout for the whole request", True
            except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError, ValueError) as exc:
                res.detail = type(exc).__name__
                res.transient = isinstance(exc, TRANSIENT)
            else:
                res.status, res.headers, nbytes = out["status"], out["headers"], out["nbytes"]
                body = out["body"]
                if body is not None:
                    res.body = body[:limit]
                    res.outcome = "too_large" if len(body) > limit else "ok"
                else:
                    res.outcome = self._status_outcome(out["status"], out.get("ctype", ""), kind)
            if kind == "page" and res.outcome == "ok" and res.body and is_gated(res.body):
                res.outcome = "gated"
            self.history.record(url, res.status, at)
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
        """One URL's requests, serialised; a result from this run is reused. Keyed on the
        exact URL, so `/dir` -> `/dir/` and http -> https redirects are followed (v1 M7); the
        request budget is still counted per page, as the audit counts it."""
        slot = self.history.slot(url)
        with slot.lock:
            if slot.result is not None:
                return replace(slot.result, hops=[])
            r = self._attempts(url, kind, limit)
            slot.result = r
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
            if r.status in (429, 503) and r.headers.get("retry-after"):
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
                parts = urlsplit(nxt)
                if parts.scheme not in ("http", "https") or not parts.hostname:
                    return FetchResult(
                        url,
                        current,
                        "fetch_error",
                        r.status,
                        hops=hops,
                        detail="redirect to a non-web scheme",
                    )
                if parts.username or parts.password:  # never send credentials (B8)
                    return FetchResult(
                        url,
                        current,
                        "fetch_error",
                        r.status,
                        hops=hops,
                        detail="redirect carrying credentials",
                    )
                hops.append(nxt)
                current = nxt
                continue
            r.url, r.final_url, r.hops = url, current, hops
            return r
        return FetchResult(url, current, "fetch_error", hops=hops, detail="too many redirects")
