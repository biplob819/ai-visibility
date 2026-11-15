"""The run log: one JSON line per stage event, from a single writer (Tech Spec §3.1, STO-02)."""

from __future__ import annotations

import datetime as dt
import json
import math
import threading
from pathlib import Path
from typing import Any


class LedgerError(ValueError):
    """A ledger event with an impossible value."""


def check_money(value: float, what: str = "cost_usd") -> float:
    """Every money value is finite and non-negative before it is recorded or capped (L-7)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise LedgerError(f"{what} must be a finite number, got {value!r}")
    if value < 0:
        raise LedgerError(f"{what} cannot be negative, got {value!r}")
    return float(value)


RESERVED = {"at", "stage", "key", "cache_hit", "latency_ms", "cost_usd", "error"}


class Ledger:
    """Appends to `<run_dir>/run.log`. Safe to call from many threads: one lock, one write per
    line, so lines never interleave."""

    def __init__(self, run_dir: Path) -> None:
        self.path = Path(run_dir) / "run.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def event(
        self,
        stage: str,
        key: str,
        *,
        cache_hit: bool,
        latency_ms: int,
        cost_usd: float,
        error: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        clash = sorted(set(extra) & RESERVED)
        if clash:
            raise LedgerError(f"extra fields cannot replace {clash}")
        for name, value in extra.items():
            if name.endswith("_usd") and value is not None:
                check_money(value, name)
        if isinstance(latency_ms, bool) or not isinstance(latency_ms, int) or latency_ms < 0:
            raise LedgerError(f"latency_ms must be a non-negative integer, got {latency_ms!r}")
        row = {
            "at": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "stage": stage,
            "key": key,
            "cache_hit": bool(cache_hit),
            "latency_ms": latency_ms,
            "cost_usd": check_money(cost_usd),
            "error": error,
            **extra,
        }
        line = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
        return row

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x]
