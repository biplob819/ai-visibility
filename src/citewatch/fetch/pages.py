"""Fetch cited pages once across runs (Tech Spec §3, §7.2, FET-05..07).

The store's `fetch` stage is keyed on the canonical URL alone, so a page is fetched once for
the whole study. The record holds the outcome, status, final URL, selected headers, robots
decision, redirect hops and whatever `analyse` returns (date candidates, A2.3), never the
body. The body stays in memory for `analyse` and is dropped; for support-sample URLs the main
text is written to the body cache for M3.2 and hand labelling.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from citewatch.store import RawStore, stage_key

from .client import FetchResult, PoliteClient
from .keys import clean, host_of

FETCH_CODE_VERSION = "fetch-2"  # fetch-2: date candidates stored (A2.3)
MAX_HOSTS_IN_FLIGHT = 8


def fetch_key(url: str) -> str:
    return stage_key("fetch", FETCH_CODE_VERSION, {"url": url}, "")


@dataclass(frozen=True)
class Page:
    """What `analyse` sees: the decoded HTML is in memory only."""

    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    html: str
    fetched_at: dt.datetime


@dataclass
class PagesResult:
    fetched: int = 0
    cached: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    errors: list[dict[str, str]] = field(default_factory=list)
    interrupted: bool = False


def body_cache_dir() -> Path:
    env = os.environ.get("CITEWATCH_BODY_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "citewatch" / "bodies"


class _Text(HTMLParser):
    # markup and page furniture: navigation, footers and forms are never evidence (SUP-02)
    SKIP = frozenset(
        {
            "script",
            "style",
            "noscript",
            "template",
            "svg",
            "head",
            "nav",
            "footer",
            "form",
            "button",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    # block elements end a line, so paragraphs and list items never run together
    # ("healthy dietNot all…", which broke sentence splitting and quote checks; D-61)
    BLOCK = frozenset(
        {
            "p",
            "div",
            "br",
            "li",
            "ul",
            "ol",
            "tr",
            "td",
            "th",
            "dd",
            "dt",
            "dl",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "section",
            "article",
            "aside",
            "header",
            "main",
            "figure",
            "figcaption",
            "blockquote",
            "table",
            "hr",
            "address",
            "details",
            "summary",
            "pre",
        }
    )

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if tag in self.BLOCK:  # <br/>, <hr/>
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def main_text(html: str) -> str:
    """Visible text with scripts, styles and markup removed, whitespace collapsed."""
    p = _Text()
    p.feed(html)
    p.close()
    lines = (re.sub(r"[ \t\f\v]+", " ", x).strip() for x in "".join(p.parts).splitlines())
    return "\n".join(x for x in lines if x)


def decode(body: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w.-]+)", content_type, re.I)
    for enc in (m.group(1) if m else None, "utf-8"):
        if enc:
            try:
                return body.decode(enc, errors="replace")
            except (LookupError, UnicodeError, ValueError):  # charset=idna, undefined (v6 M3)
                continue
    return body.decode("utf-8", errors="replace")


def _record(r: FetchResult, extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "url": r.url,
        "final_url": None if r.final_url is None else clean(r.final_url),
        "outcome": r.outcome,
        "status": r.status,
        "headers": {k: clean(v) for k, v in r.headers.items()},
        "robots": r.robots,
        "hops": [clean(h) for h in r.hops],
        "fetched_at": None
        if r.fetched_at is None
        else r.fetched_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "detail": None if r.detail is None else clean(r.detail),
        **extra,
    }


def fetch_pages(
    urls: Iterable[str],
    *,
    client: PoliteClient,
    store: RawStore,
    analyse: Callable[[Page], dict[str, Any]] | None = None,
    keep_text: frozenset[str] = frozenset(),
    body_cache: Path | None = None,
    stop: threading.Event | None = None,
) -> PagesResult:
    """Fetch every URL not already in the store, one host per worker, at most 8 hosts."""
    stop = stop or threading.Event()
    result = PagesResult()
    lock = threading.Lock()
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in dict.fromkeys(urls):  # each canonical URL once, input order kept
        by_host[host_of(u)].append(u)

    def one(url: str) -> None:
        key = fetch_key(url)
        if store.has("fetch", key):
            with lock:
                result.cached += 1
            return
        r = client.get(url, "page")
        extra: dict[str, Any] = {}
        if r.outcome == "ok" and r.body is not None and r.status is not None:
            try:
                html = decode(r.body, r.headers.get("content-type", ""))
            except Exception as exc:  # a fetched page always gets its record
                html = ""
                extra = {"analyse_error": f"{type(exc).__name__}: {exc}"[:300]}
            page = Page(
                url,
                r.final_url or url,
                r.status,
                dict(r.headers),
                html,
                r.fetched_at or dt.datetime.now(dt.UTC),
            )
            if analyse is not None:
                try:
                    extra = dict(analyse(page))
                except Exception as exc:  # a parser bug never loses the fetch record
                    extra = {"analyse_error": f"{type(exc).__name__}: {exc}"[:300]}
            if url in keep_text:
                try:
                    d = body_cache or body_cache_dir()
                    d.mkdir(parents=True, exist_ok=True)
                    (d / ".citewatch-body-cache").touch()  # finalise deletes only marked caches
                    name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".txt"
                    (d / name).write_text(main_text(html), encoding="utf-8")
                except (OSError, ValueError) as exc:  # the record is kept even so
                    extra["text_cache_error"] = f"{type(exc).__name__}: {exc}"[:300]
            del html, page
        r.body = None  # dropped here: nothing below sees the body
        store.put("fetch", key, _record(r, extra))
        with lock:
            result.fetched += 1
            result.outcomes[r.outcome] += 1

    def host_worker(host_urls: list[str]) -> None:
        for u in host_urls:
            if stop.is_set():
                return
            try:
                one(u)
            except Exception as exc:  # one bad page never stops the host
                with lock:
                    result.errors.append({"url": u, "error": f"{type(exc).__name__}: {exc}"})

    pool = ThreadPoolExecutor(max_workers=MAX_HOSTS_IN_FLIGHT)
    try:
        futures = [pool.submit(host_worker, us) for us in by_host.values()]
        pending = set(futures)
        while pending:
            _done, pending = wait(pending, timeout=0.5)
    except KeyboardInterrupt:
        stop.set()
        result.interrupted = True
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return result
