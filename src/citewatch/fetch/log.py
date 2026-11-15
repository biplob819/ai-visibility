"""The fetch log: one JSON line per request or robots refusal (Tech Spec §7.2, FET-08)."""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

from .keys import clean, host_of

FIELDS = ("url", "host", "at", "attempt", "status", "bytes", "robots", "outcome", "user_agent")


class FetchLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(
        self,
        *,
        url: str,
        at: dt.datetime,
        attempt: int,
        status: int | None,
        nbytes: int | None,
        robots: str,
        outcome: str,
        user_agent: str,
    ) -> dict[str, Any]:
        if at.tzinfo is None:
            raise ValueError("fetch log times must be timezone-aware")
        row = {
            "url": clean(url),
            "host": host_of(url),
            "at": at.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "attempt": attempt,
            "status": status,
            "bytes": nbytes,
            "robots": robots,
            "outcome": outcome,
            "user_agent": user_agent,
        }
        line = json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
        return row

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        text = self.path.read_text(encoding="utf-8")
        return [json.loads(x) for x in text.splitlines() if x.strip()]
