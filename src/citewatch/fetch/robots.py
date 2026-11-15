"""robots.txt per origin, parsed with protego (RFC 9309 longest match, D-10, FET-01).

Status rules (Tech Spec §7.2): 2xx parses; 404, 410 and other 4xx allow everything; 401 and
403 disallow everything (stricter than RFC 9309, on purpose); 5xx, a timeout, a transport
error, too many redirects or a redirect away from a robots.txt disallow everything.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from protego import Protego

from citewatch.store import stage_key

from .keys import ascii_host, clean

ROBOTS_TOKEN = "citewatch"
MAX_ROBOTS_BYTES = 512 * 1024  # RFC 9309 asks crawlers to parse at least 500 KiB


@dataclass(frozen=True)
class RobotsRules:
    mode: str  # "parsed", "allow_all", "deny_all"
    status: int | None
    parser: Protego | None = None

    def allows(self, url: str) -> bool:
        if self.mode == "allow_all":
            return True
        if self.mode == "deny_all" or self.parser is None:
            return False
        return bool(self.parser.can_fetch(url, ROBOTS_TOKEN))


def rules_from(status: int | None, text: str | None) -> RobotsRules:
    if status is None:
        return RobotsRules("deny_all", None)
    if 200 <= status < 300:
        return RobotsRules("parsed", status, Protego.parse(text or ""))
    if status in (401, 403):
        return RobotsRules("deny_all", status)
    if 400 <= status < 500:
        return RobotsRules("allow_all", status)
    return RobotsRules("deny_all", status)  # 5xx, or a 3xx that could not be followed


def origin_of(url: str) -> str:
    p = urlsplit(url)
    host = ascii_host(p.hostname or "")
    shown = f"[{host}]" if ":" in host else host
    port = p.port
    default = {"http": 80, "https": 443}.get(p.scheme.lower())
    return f"{p.scheme.lower()}://{shown}" + ("" if port in (None, default) else f":{port}")


ROBOTS_CODE_VERSION = "robots-2"  # robots-2: only directive lines are kept
_DIRECTIVE = re.compile(r"^\s*(user-agent|allow|disallow|sitemap|crawl-delay)\s*:", re.I)
MAX_DIRECTIVES = 5000


def directives(text: str) -> list[str]:
    """The robots.txt lines protego reads, nothing else: a soft-404 HTML page served as
    robots.txt keeps no markup (NFR6) and reads as allow-all, as protego would read it."""
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if _DIRECTIVE.match(line) and len(line) <= 2000:
            # percent-encode angle brackets: no markup is ever stored (v2 M-2), and request
            # paths carry them encoded anyway, so matching is unchanged
            out.append(
                clean(line)
            )  # escaped markup (`&lt;html`) and JSON- or dict-looking keys too (v3 M3, v4 M1)
            if len(out) >= MAX_DIRECTIVES:
                break
    return out


class RobotsCache:
    """Fetches each origin's robots.txt once for the whole study (concurrent askers wait for
    the first). With a store, the answer is kept under the `robots` stage keyed on the origin,
    so later runs and resumed fetches never ask again (the audit counts those requests too)."""

    def __init__(
        self, fetch: Callable[[str], tuple[int | None, str | None]], store: Any = None
    ) -> None:
        self._fetch = fetch
        self._store = store
        self._rules: dict[str, RobotsRules] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def rules(self, url: str) -> RobotsRules:
        origin = origin_of(url)
        with self._lock:
            if origin in self._rules:
                return self._rules[origin]
            olock = self._locks.setdefault(origin, threading.Lock())
        with olock:
            with self._lock:
                if origin in self._rules:
                    return self._rules[origin]
            key = stage_key("robots", ROBOTS_CODE_VERSION, {"origin": origin}, "")
            if self._store is not None and self._store.has("robots", key):
                saved = self._store.get("robots", key)
                status, text = saved["status"], "\n".join(saved["directives"])
            else:
                try:
                    status, text = self._fetch(origin + "/robots.txt")
                except Exception:  # an unexpected failure disallows, and is cached
                    status, text = None, None
                text = None if text is None else "\n".join(directives(text))
                if self._store is not None:
                    self._store.put(
                        "robots",
                        key,
                        {
                            "origin": clean(origin),
                            "status": status,
                            "directives": [] if text is None else text.splitlines(),
                        },
                    )
            r = rules_from(status, text)
            with self._lock:
                self._rules[origin] = r
            return r

    def allows(self, url: str) -> bool:
        return self.rules(url).allows(url)
