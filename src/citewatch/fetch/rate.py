"""One request per second per host, and at most 8 in flight (Tech Spec §7.2, FET-02).

A grant is taken immediately before the request is sent and its time is the request's `at`.
Grants for one host are spaced by the interval plus a small margin on the monotonic clock, so
wall-clock `at` values in the log stay at least the interval apart.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from .keys import norm_host

INTERVAL_S = 1.0
MARGIN_S = 0.02
MAX_IN_FLIGHT = 8


class HostLimiter:
    def __init__(
        self,
        interval: float = INTERVAL_S,
        margin: float = MARGIN_S,
        max_in_flight: int = MAX_IN_FLIGHT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.interval, self.margin = interval, margin
        self._clock, self._sleep = clock, sleep
        self._wall = wall or (lambda: dt.datetime.now(dt.UTC))
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_in_flight)
        self.live = self.max_live = 0

    @contextmanager
    def request(self, host: str) -> Iterator[dt.datetime]:
        """Hold one in-flight slot and this host's next grant; yields the request start time."""
        host = norm_host(host)
        with self._slots:
            while True:
                with self._lock:
                    now = self._clock()
                    nxt = self._next.get(host, float("-inf"))
                    if now >= nxt:
                        self._next[host] = now + self.interval + self.margin
                        at = self._wall()
                        self.live += 1
                        self.max_live = max(self.max_live, self.live)
                        break
                    wait = nxt - now
                self._sleep(wait)
            try:
                yield at
            finally:
                with self._lock:
                    self.live -= 1
