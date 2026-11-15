"""What has already happened to each page, across runs (FET-04).

Seeded from every earlier fetch log of the study, with the audit's page identity, so the
fetcher never makes a fourth request for a page, never asks again after a block or a robots
refusal, and reuses a result already fetched in this run.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .keys import host_of, norm_url, page_key

MAX_REQUESTS = 3  # one try and two retries, for the whole study
BLOCK_STATUSES = frozenset({401, 403, 451})


@dataclass
class _Entry:
    requests: int = 0
    blocked: bool = False
    robots_refused: bool = False
    result: Any = None
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class _Slot:
    result: Any = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class PageHistory:
    def __init__(self) -> None:
        self._pages: dict[str, _Entry] = {}
        self._slots: dict[str, _Slot] = {}
        self.last_at: dict[str, dt.datetime] = {}  # host -> last request start, all runs
        self._lock = threading.Lock()

    @classmethod
    def from_logs(cls, paths: Iterable[Path]) -> PageHistory:
        h = cls()
        for p in paths:
            if not Path(p).is_file():
                continue
            raw = Path(p).read_bytes()
            if raw[:2] == b"\x1f\x8b":  # an archived .jsonl.gz counts too (v2 L-4)
                raw = gzip.decompress(raw)
            for line in raw.decode("utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # a torn line never stops later fetches; the audit reports it
                if isinstance(row, dict) and isinstance(row.get("url"), str):
                    h.seed(row)
        return h

    def seed(self, row: dict[str, Any]) -> None:
        e = self.entry(row["url"])
        if row.get("outcome") == "robots_disallowed":
            e.robots_refused = True
        else:
            e.requests += 1
            if row.get("status") in BLOCK_STATUSES:
                e.blocked = True
            try:
                at = dt.datetime.fromisoformat(str(row.get("at")).replace("Z", "+00:00"))
            except ValueError:
                return
            if at.tzinfo is not None:
                self._note_at(row["url"], at)

    def entry(self, url: str) -> _Entry:
        key = page_key(url)
        with self._lock:
            return self._pages.setdefault(key, _Entry())

    def may_request(self, url: str) -> str | None:
        """None when a request is allowed, else the reason it is not."""
        e = self.entry(url)
        if e.blocked:
            return "blocked earlier"
        if e.robots_refused:
            return "refused by robots earlier"
        if e.requests >= MAX_REQUESTS:
            return "request budget for this page used"
        return None

    def record(self, url: str, status: int | None, at: dt.datetime | None = None) -> None:
        e = self.entry(url)
        e.requests += 1
        if status in BLOCK_STATUSES:
            e.blocked = True
        if at is not None:
            self._note_at(url, at)

    def _note_at(self, url: str, at: dt.datetime) -> None:
        host = host_of(url)
        with self._lock:
            if host not in self.last_at or at > self.last_at[host]:
                self.last_at[host] = at

    def slot(self, url: str) -> _Slot:
        """This run's result for one exact (normalised) URL."""
        key = norm_url(url)
        with self._lock:
            return self._slots.setdefault(key, _Slot())

    def refuse(self, url: str) -> None:
        self.entry(url).robots_refused = True
