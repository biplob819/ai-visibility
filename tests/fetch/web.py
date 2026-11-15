"""A fake web for the fetcher: an httpx MockTransport with scripted responses per URL, a
virtual clock for the rate limiter, and the gate-8 audit run over every log (no network)."""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

import fetch_audit
from citewatch.fetch import FetchLog, HostLimiter, PageHistory, PoliteClient
from citewatch.store import RawStore

UA = "citewatch/0.1.0 (+https://github.com/biplob819/ai-visibility)"
BASE = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.UTC)
HTML = {"content-type": "text/html; charset=utf-8"}
PAGE = b"<html><head><title>T</title></head><body><p>Hello page</p></body></html>"


class VClock:
    """Time moves only when someone sleeps, so 1 s spacing costs nothing in tests."""

    def __init__(self) -> None:
        self.t = 0.0
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self.t

    def sleep(self, s: float) -> None:
        with self._lock:
            self.t += max(0.0, s)

    def wall(self) -> dt.datetime:
        return BASE + dt.timedelta(seconds=self.now())


Reply = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class FakeWeb:
    def __init__(self, routes: Mapping[str, Any] | None = None, delay: float = 0.0):
        self.routes: dict[str, list[Reply]] = {}
        for url, r in (routes or {}).items():
            self.add(url, r)
        self.requests: list[httpx.Request] = []
        self.delay = delay
        self.live = self.max_live = 0
        self._lock = threading.Lock()

    def add(self, url: str, reply: Reply | list[Reply]) -> None:
        self.routes[url] = list(reply) if isinstance(reply, list) else [reply]

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
            self.live += 1
            self.max_live = max(self.max_live, self.live)
        try:
            if self.delay:
                time.sleep(self.delay)
            url = str(request.url)
            queue = self.routes.get(url)
            if queue is None:
                if request.url.path == "/robots.txt":
                    return httpx.Response(404)
                return httpx.Response(200, headers=HTML, content=PAGE)
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(reply, Exception):
                raise reply
            if callable(reply) and not isinstance(reply, httpx.Response):
                return reply(request)
            return httpx.Response(reply.status_code, headers=reply.headers, content=reply.content)
        finally:
            with self._lock:
                self.live -= 1


def make(
    tmp_path: Path,
    web: FakeWeb,
    *,
    history: PageHistory | None = None,
    store: RawStore | None = None,
    **kw: Any,
) -> tuple[PoliteClient, FetchLog, VClock]:
    clock = VClock()
    limiter = HostLimiter(clock=clock.now, sleep=clock.sleep, wall=clock.wall)
    log = FetchLog(tmp_path / "data" / "fetch_log.jsonl")
    client = PoliteClient(
        UA,
        log,
        limiter=limiter,
        history=history,
        transport=httpx.MockTransport(web.handler),
        sleep=clock.sleep,
        store=store,
        **kw,
    )
    return client, log, clock


def audit(log: FetchLog) -> list[str]:
    """The gate-8 audit's verdict on a log: [] when it passes."""
    return fetch_audit.audit_paths([log.path])
