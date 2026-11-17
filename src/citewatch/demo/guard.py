"""The live-mode spend guard (DEM-02, DEM-05; the design of EvalKit's D3.1 guard).

Every live request passes, in order, before any model call: a signed-in identity, the
per-request cap (always, whoever pays: it protects a visitor's own keys too), the identity's
rate limit, and, only for requests on the owner's keys, the owner's daily cap. The daily cap is
enforced by holding the request's bound against today's counter with one atomic check-and-add
in the shared KV, so concurrent requests can never pass it together and the counter survives
app restarts. After the call the hold is settled to the actual cost. Requests on a visitor's
own keys are never counted against the owner's budget (OWNER D-58).
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from citewatch.demo.kv import KV

DAILY_CAP_USD = 3.0  # Tech Spec §9
PER_REQUEST_CAP_USD = 0.50  # the planning bound for one question on both models is about $0.43
RATE_LIMIT = 5  # live requests per signed-in passkey per window
RATE_WINDOW_S = 3600
SPEND_TTL_S = 3 * 24 * 3600  # a day's counter outlives the day, then expires
MICRO = 1_000_000
LOG = logging.getLogger("citewatch.demo")

STORE_DOWN = (
    "The live budget store is unavailable right now; try again later. Lookup mode always works."
)


class GuardRefused(Exception):
    """A live request refused before any model call. `reason` is safe to show the visitor."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def micro(usd: float) -> int:
    """Dollars as whole micro-dollars, rounded up so a hold is never smaller than its bound."""
    if not (usd >= 0 and math.isfinite(usd)):  # also rejects NaN and infinity
        raise ValueError(f"money must be a non-negative number, got {usd!r}")
    return math.ceil(round(usd * MICRO, 3))


def identity_key(identity: str) -> str:
    """A short, one-way name for a signed-in identity in rate-limit keys."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class Ticket:
    """An admitted live request. `owner` holds `reserved` micro-dollars of today's budget."""

    day: str
    reserved: int
    owner: bool


class SpendGuard:
    def __init__(
        self,
        kv: KV,
        *,
        per_request_cap: float = PER_REQUEST_CAP_USD,
        daily_cap: float = DAILY_CAP_USD,
        rate_limit: int = RATE_LIMIT,
        rate_window_s: int = RATE_WINDOW_S,
        clock: Callable[[], float] = time.time,
        today: Callable[[], str] = lambda: datetime.now(UTC).date().isoformat(),
    ) -> None:
        if per_request_cap <= 0 or daily_cap <= 0 or rate_limit <= 0:
            raise ValueError("caps and the rate limit must be positive")
        self.kv = kv
        self.per_request_cap = per_request_cap
        self.daily_cap = daily_cap
        self.rate_limit = rate_limit
        self.rate_window_s = rate_window_s
        self._clock = clock
        self._today = today

    def check_cap(self, bound_usd: float) -> None:
        if bound_usd > self.per_request_cap:
            raise GuardRefused(
                f"This request could cost up to ${bound_usd:.2f}, over the "
                f"${self.per_request_cap:.2f} per-request limit."
            )

    def _take_rate_slot(self, identity: str) -> None:
        window = int(self._clock() // self.rate_window_s)
        key = f"rate:{identity_key(identity)}:{window}"
        try:
            n = self.kv.incr(key, 1, self.rate_window_s * 2)
        except Exception as exc:
            LOG.warning("demo store unavailable (%s)", type(exc).__name__)
            raise GuardRefused(STORE_DOWN) from None
        if n > self.rate_limit:
            raise GuardRefused(
                f"Rate limit: {self.rate_limit} live questions per "
                f"{self.rate_window_s // 60} minutes for each passkey."
            )

    def reserve(self, identity: str, bound_usd: float, *, owner_keys: bool) -> Ticket:
        """Refuse (GuardRefused) or admit one request; nothing is called before this returns.
        On the owner's keys, `bound_usd` is held against today's budget until `settle`."""
        if not identity:
            raise GuardRefused("Sign in with your passkey first.")
        self.check_cap(bound_usd)  # first, so a refused request takes no rate-limit slot
        self._take_rate_slot(identity)
        day = self._today()
        if not owner_keys:
            return Ticket(day=day, reserved=0, owner=False)
        hold = micro(bound_usd)
        try:
            held = self.kv.add_within(f"spend:{day}", hold, micro(self.daily_cap), SPEND_TTL_S)
        except Exception as exc:  # never echo the store's message: it can quote the URL
            LOG.warning("demo store unavailable (%s)", type(exc).__name__)
            raise GuardRefused(STORE_DOWN) from None
        if not held:
            raise GuardRefused(
                "Today's live budget on the owner's keys is used up. You can use your own API "
                "keys, or come back tomorrow; lookup mode always works."
            )
        return Ticket(day=day, reserved=hold, owner=True)

    def settle(self, ticket: Ticket, actual_usd: float) -> None:
        """Replace the hold with the actual cost. A store failure keeps the whole hold, so the
        day is overcounted, never undercounted."""
        if not ticket.owner:
            return
        try:
            self.kv.incr(
                f"spend:{ticket.day}", micro(max(0.0, actual_usd)) - ticket.reserved, SPEND_TTL_S
            )
        except Exception as exc:
            LOG.warning("demo spend settle failed (%s); hold kept", type(exc).__name__)

    def spent_today(self) -> float:
        return self.kv.get_int(f"spend:{self._today()}") / MICRO

    def remaining_today(self) -> float | None:
        """Today's owner budget not yet spent or held; None when the store cannot be read."""
        try:
            return max(0.0, self.daily_cap - self.spent_today())
        except Exception as exc:
            LOG.warning("demo store unavailable (%s)", type(exc).__name__)
            return None
