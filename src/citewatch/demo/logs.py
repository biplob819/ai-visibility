"""Aggregate-only request logging (DEM-03, Tech Spec §9 Privacy).

One line per lookup or live request with exactly four fields: timestamp, mode, latency and
cost. Never the question or domain typed, an IP address, a session or passkey id, an API key,
a model's answer or a provider's error message.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

LOG = logging.getLogger("citewatch.demo")
FIELDS = ("at", "mode", "latency_ms", "cost_usd")
MODES = frozenset({"lookup", "live-owner-keys", "live-own-keys"})


def log_request(
    mode: str,
    latency_ms: float,
    cost_usd: float,
    *,
    logger: logging.Logger = LOG,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Write one aggregate record and return it. Raises ValueError for an unknown mode, so no
    free text can reach the log through it."""
    if mode not in MODES:
        raise ValueError(f"unknown demo mode {mode!r}")
    cost = float(cost_usd)
    record = {
        "at": now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "mode": mode,
        "latency_ms": max(0, int(latency_ms)),
        "cost_usd": round(cost, 6) if math.isfinite(cost) and cost >= 0 else 0.0,
    }
    logger.info(json.dumps(record, sort_keys=True))
    return record
