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

from .keys import ascii_host

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
        self._last_wall: dict[str, dt.datetime] = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_in_flight)
        self.live = self.max_live = 0

    def seed(self, host: str, last_at: dt.datetime) -> None:
        """A request to `host` started at `last_at` (wall clock), e.g. in an earlier run."""
        wait = last_at + dt.timedelta(seconds=self.interval + self.margin) - self._wall()
        with self._lock:
            key = ascii_host(host)
            nxt = self._clock() + max(0.0, wait.total_seconds())
            self._next[key] = max(self._next.get(key, float("-inf")), nxt)
            if key not in self._last_wall or last_at > self._last_wall[key]:
                self._last_wall[key] = last_at

    @contextmanager
    def request(self, host: str) -> Iterator[dt.datetime]:
        """Hold one in-flight slot and this host's next grant; yields the request start time."""
        host = ascii_host(host)
        gap = self.interval + self.margin
        with self._slots:
            while True:
                with self._lock:
                    now = self._clock()
                    wall = self._wall()
                    nxt = self._next.get(host, float("-inf"))
                    last = self._last_wall.get(host)
                    wall_wait = 0.0 if last is None else gap - (wall - last).total_seconds()
                    if now >= nxt and wall_wait <= 0:
                        # spaced on both clocks: the logged `at` (this wall reading) is at
                        # least the interval after the last one, even after a pause (v2 M-1)
                        self._next[host] = now + gap
                        self._last_wall[host] = wall
                        at = wall
                        self.live += 1
                        self.max_live = max(self.max_live, self.live)
                        break
                    wait = max(nxt - now, wall_wait)
                self._sleep(wait)
            try:
                yield at
            finally:
                with self._lock:
                    self.live -= 1
