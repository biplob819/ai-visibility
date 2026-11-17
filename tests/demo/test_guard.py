"""DEM-02, DEM-05: the spend guard (per-request cap, per-passkey rate limit, the owner's daily
cap counting only calls on the owner's keys) and the store it keeps its counters in."""

from __future__ import annotations

import json
import threading

import httpx
import pytest

from citewatch.demo.guard import (
    DAILY_CAP_USD,
    STORE_DOWN,
    GuardRefused,
    SpendGuard,
    micro,
)
from citewatch.demo.kv import ADD_WITHIN_SCRIPT, INCR_SCRIPT, PREFIX, KVError, SqliteKV, UpstashKV


class Clock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def kv(tmp_path):
    return SqliteKV(tmp_path / "demo.sqlite")


def guard(kv, **kw) -> SpendGuard:
    kw.setdefault("today", lambda: "2026-11-17")
    kw.setdefault("rate_limit", 100)
    return SpendGuard(kv, **kw)


def test_defaults_match_the_spec(kv):
    g = SpendGuard(kv)
    assert g.daily_cap == DAILY_CAP_USD == 3.0
    assert 0 < g.per_request_cap <= 1.0


@pytest.mark.safety
def test_per_request_cap_applies_on_owner_and_own_keys(kv):
    g = guard(kv, per_request_cap=0.50)
    for owner in (True, False):
        with pytest.raises(GuardRefused, match="per-request limit"):
            g.reserve("pk1", 0.51, owner_keys=owner)
    assert g.spent_today() == 0


@pytest.mark.safety
def test_daily_cap_counts_owner_keys_only(kv):
    g = guard(kv, per_request_cap=1.0, daily_cap=3.0)
    tickets = [g.reserve("pk1", 1.0, owner_keys=True) for _ in range(3)]
    assert g.spent_today() == pytest.approx(3.0)
    with pytest.raises(GuardRefused, match="budget on the owner's keys is used up"):
        g.reserve("pk1", 1.0, owner_keys=True)
    # the visitor's own keys still work and add nothing to the owner's counter
    own = g.reserve("pk1", 1.0, owner_keys=False)
    assert not own.owner and own.reserved == 0
    g.settle(own, 0.9)
    assert g.spent_today() == pytest.approx(3.0)
    # settling owner tickets to their actual cost frees the unused hold
    for t in tickets:
        g.settle(t, 0.25)
    assert g.spent_today() == pytest.approx(0.75)
    assert g.remaining_today() == pytest.approx(2.25)


def test_settle_can_raise_the_counter_above_the_hold(kv):
    g = guard(kv, per_request_cap=1.0)
    t = g.reserve("pk1", 0.4, owner_keys=True)
    g.settle(t, 0.6)  # the actual cost wins: overcount never undercount
    assert g.spent_today() == pytest.approx(0.6)


def test_daily_cap_survives_a_restart(tmp_path):
    path = tmp_path / "demo.sqlite"
    guard(SqliteKV(path), per_request_cap=2.0).reserve("pk1", 2.0, owner_keys=True)
    g2 = guard(SqliteKV(path), per_request_cap=2.0)
    assert g2.spent_today() == pytest.approx(2.0)
    with pytest.raises(GuardRefused):
        g2.reserve("pk1", 1.5, owner_keys=True)


def test_concurrent_reservations_never_pass_the_daily_cap(kv):
    g = guard(kv, per_request_cap=0.5, daily_cap=3.0)
    ok: list[bool] = []

    def one() -> None:
        try:
            g.reserve("pk1", 0.5, owner_keys=True)
            ok.append(True)
        except GuardRefused:
            ok.append(False)

    threads = [threading.Thread(target=one) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ok.count(True) == 6
    assert g.spent_today() == pytest.approx(3.0)


def test_the_day_rolls_over(kv):
    day = ["2026-11-17"]
    g = guard(kv, per_request_cap=3.0, today=lambda: day[0])
    g.reserve("pk1", 3.0, owner_keys=True)
    with pytest.raises(GuardRefused):
        g.reserve("pk1", 0.1, owner_keys=True)
    day[0] = "2026-11-18"
    assert g.reserve("pk1", 0.1, owner_keys=True).owner


@pytest.mark.safety
def test_rate_limit_is_per_passkey_and_applies_on_own_keys(kv):
    clock = Clock()
    g = guard(kv, rate_limit=2, clock=clock)
    g.reserve("pk1", 0.1, owner_keys=False)
    g.reserve("pk1", 0.1, owner_keys=True)
    with pytest.raises(GuardRefused, match="Rate limit"):
        g.reserve("pk1", 0.1, owner_keys=False)
    g.reserve("pk2", 0.1, owner_keys=False)  # another passkey has its own allowance
    clock.t += g.rate_window_s
    g.reserve("pk1", 0.1, owner_keys=False)


def test_a_capped_request_takes_no_rate_slot(kv):
    g = guard(kv, rate_limit=1, per_request_cap=0.5)
    with pytest.raises(GuardRefused, match="per-request"):
        g.reserve("pk1", 0.9, owner_keys=True)
    g.reserve("pk1", 0.1, owner_keys=True)


def test_no_identity_no_request(kv):
    with pytest.raises(GuardRefused, match="Sign in"):
        guard(kv).reserve("", 0.1, owner_keys=False)


@pytest.mark.safety
def test_store_down_refuses_without_echoing_the_store(kv, monkeypatch):
    g = guard(kv)

    def boom(*a, **k):
        raise KVError("https://secret.upstash.io token abc")

    monkeypatch.setattr(kv, "incr", boom)
    with pytest.raises(GuardRefused) as exc:
        g.reserve("pk1", 0.1, owner_keys=True)
    assert exc.value.reason == STORE_DOWN
    monkeypatch.setattr(kv, "get_int", boom)
    assert g.remaining_today() is None


def test_micro_dollars_round_up_and_reject_bad_money():
    assert micro(0.4) == 400_000
    assert micro(0.0000001) == 1
    for bad in (-0.1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            micro(bad)


# --- the stores ---------------------------------------------------------------------------------


def test_sqlite_counters_expire(tmp_path):
    clock = Clock()
    kv = SqliteKV(tmp_path / "x.sqlite", clock=clock)
    assert kv.incr("a", 2, 10) == 2
    assert kv.add_within("a", 3, 5, 10) and not kv.add_within("a", 1, 5, 10)
    clock.t += 11
    assert kv.get_int("a") == 0 and kv.incr("a", 1, 10) == 1
    kv.hset("h", "f", "v")
    assert kv.hget("h", "f") == "v" and kv.hget("h", "g") is None and kv.hlen("h") == 1


class FakeRedis:
    """Just enough of an Upstash REST endpoint to check the commands the client sends."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.ints: dict[str, int] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.commands: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        cmd = json.loads(request.content)
        self.commands.append(cmd)
        op = cmd[0]
        if op == "GET":
            v = self.ints.get(cmd[1])
            return httpx.Response(200, json={"result": None if v is None else str(v)})
        if op == "EVAL" and cmd[1] == INCR_SCRIPT:
            self.ints[cmd[3]] = self.ints.get(cmd[3], 0) + int(cmd[4])
            return httpx.Response(200, json={"result": self.ints[cmd[3]]})
        if op == "EVAL" and cmd[1] == ADD_WITHIN_SCRIPT:
            cur, add, cap = self.ints.get(cmd[3], 0), int(cmd[4]), int(cmd[5])
            if cur + add > cap:
                return httpx.Response(200, json={"result": 0})
            self.ints[cmd[3]] = cur + add
            return httpx.Response(200, json={"result": 1})
        if op == "HSET":
            self.hashes.setdefault(cmd[1], {})[cmd[2]] = cmd[3]
            return httpx.Response(200, json={"result": 1})
        if op == "HGET":
            return httpx.Response(200, json={"result": self.hashes.get(cmd[1], {}).get(cmd[2])})
        if op == "HLEN":
            return httpx.Response(200, json={"result": len(self.hashes.get(cmd[1], {}))})
        return httpx.Response(400, json={"error": f"unknown {op}"})


def upstash(fake: FakeRedis, token: str | None = None) -> UpstashKV:
    client = httpx.Client(transport=httpx.MockTransport(fake))
    return UpstashKV("https://example-kv.upstash.io", token or fake.token, client)


@pytest.mark.contract
def test_upstash_store_runs_the_guard_atomically_through_scripts():
    fake = FakeRedis("tok-123")
    g = guard(upstash(fake), per_request_cap=1.0, daily_cap=1.5)
    t = g.reserve("pk1", 1.0, owner_keys=True)
    with pytest.raises(GuardRefused):
        g.reserve("pk1", 1.0, owner_keys=True)
    g.settle(t, 0.2)
    assert g.spent_today() == pytest.approx(0.2)
    evals = [c for c in fake.commands if c[0] == "EVAL"]
    assert all(c[3].startswith(PREFIX) for c in evals)  # every key namespaced
    # the cap check and the add are one script, never a GET then a separate INCR
    assert any(c[1] == ADD_WITHIN_SCRIPT for c in evals)
    assert "INCRBY" in INCR_SCRIPT and "EXPIRE" in INCR_SCRIPT and "EXPIRE" in ADD_WITHIN_SCRIPT


def test_upstash_hash_commands():
    fake = FakeRedis("tok-123")
    kv = upstash(fake)
    kv.hset("passkeys", "abc", "{}")
    assert kv.hget("passkeys", "abc") == "{}" and kv.hlen("passkeys") == 1


@pytest.mark.safety
def test_upstash_errors_never_quote_the_url_or_token():
    fake = FakeRedis("right-token")
    kv = upstash(fake, token="wrong-token-xyz")
    with pytest.raises(KVError) as exc:
        kv.get_int("a")
    assert "wrong-token" not in str(exc.value) and "upstash.io" not in str(exc.value)
    assert "wrong-token" not in repr(kv) and "upstash.io" not in repr(kv)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot reach https://example-kv.upstash.io")

    broken = UpstashKV(
        "https://example-kv.upstash.io", "t", httpx.Client(transport=httpx.MockTransport(down))
    )
    with pytest.raises(KVError) as exc:
        broken.incr("a", 1, 10)
    assert "upstash.io" not in str(exc.value)


def test_upstash_needs_https_and_a_token():
    with pytest.raises(ValueError):
        UpstashKV("http://example-kv.upstash.io", "t")
    with pytest.raises(ValueError):
        UpstashKV("https://example-kv.upstash.io", "")
