"""What has already happened to each page, across runs (FET-04).

Seeded from every earlier fetch log of the study, with the audit's page identity, so the
fetcher never makes a fourth request for a page, never asks again after a block or a robots
refusal, and reuses a result already fetched in this run.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .keys import page_key

MAX_REQUESTS = 3  # one try and two retries, for the whole study
BLOCK_STATUSES = frozenset({401, 403, 451})


@dataclass
class _Entry:
    requests: int = 0
    blocked: bool = False
    robots_refused: bool = False
    result: Any = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class PageHistory:
    def __init__(self) -> None:
        self._pages: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_logs(cls, paths: Iterable[Path]) -> PageHistory:
        h = cls()
        for p in paths:
            if not Path(p).is_file():
                continue
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    h.seed(json.loads(line))
        return h

    def seed(self, row: dict[str, Any]) -> None:
        e = self.entry(row["url"])
        if row.get("outcome") == "robots_disallowed":
            e.robots_refused = True
        else:
            e.requests += 1
            if row.get("status") in BLOCK_STATUSES:
                e.blocked = True

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

    def record(self, url: str, status: int | None) -> None:
        e = self.entry(url)
        e.requests += 1
        if status in BLOCK_STATUSES:
            e.blocked = True

    def refuse(self, url: str) -> None:
        self.entry(url).robots_refused = True
