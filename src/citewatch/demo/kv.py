"""The demo's small persistent store: spend counters, rate-limit counters and passkeys.

Production uses a hosted Redis-compatible KV over its REST API (Upstash: one HTTPS POST per
command, so no driver and no open connection; httpx is already a core dependency). Local
development uses a SQLite file. Counters are integers (money in micro-dollars) and every
check-and-add is one atomic step, so concurrent sessions can never pass a cap together.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx

PREFIX = "citewatch:demo:"


class KVError(RuntimeError):
    """The store could not be reached or refused a command. The message never quotes the
    store's URL or token."""


class KV(Protocol):
    def get_int(self, key: str) -> int: ...

    def incr(self, key: str, by: int, ttl_s: int) -> int:
        """Add `by` (may be negative) and return the new value; the key expires `ttl_s` after
        its last change."""
        ...

    def add_within(self, key: str, by: int, cap: int, ttl_s: int) -> bool:
        """Add `by` only if the result stays at or under `cap`, atomically."""
        ...

    def hget(self, key: str, field: str) -> str | None: ...

    def hset(self, key: str, field: str, value: str) -> None: ...

    def hlen(self, key: str) -> int: ...


# One Lua script per atomic step: Redis runs a script without interleaving other commands.
INCR_SCRIPT = (
    "local v = redis.call('INCRBY', KEYS[1], ARGV[1]) "
    "redis.call('EXPIRE', KEYS[1], ARGV[2]) "
    "return v"
)
ADD_WITHIN_SCRIPT = (
    "local cur = tonumber(redis.call('GET', KEYS[1]) or '0') "
    "local add = tonumber(ARGV[1]) "
    "if cur + add > tonumber(ARGV[2]) then return 0 end "
    "redis.call('INCRBY', KEYS[1], add) "
    "redis.call('EXPIRE', KEYS[1], ARGV[3]) "
    "return 1"
)


class UpstashKV:
    """A Redis-compatible KV behind an Upstash-style REST endpoint: POST the command as a JSON
    array with a bearer token, read `{"result": ...}` or `{"error": ...}`."""

    def __init__(self, url: str, token: str, client: httpx.Client | None = None) -> None:
        if not url.startswith("https://"):
            raise ValueError("the KV URL must be an https:// REST endpoint")
        if not token:
            raise ValueError("the KV needs a token")
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client or httpx.Client(timeout=5.0)

    def __repr__(self) -> str:  # never the URL or the token
        return "UpstashKV(<configured>)"

    def _cmd(self, *args: Any) -> Any:
        try:
            r = self._client.post(self._url, json=[str(a) for a in args], headers=self._headers)
            body = r.json()
        except Exception as exc:  # connection, timeout, not JSON: name the kind only
            raise KVError(f"KV unreachable ({type(exc).__name__})") from None
        if r.status_code != 200 or not isinstance(body, dict) or "error" in body:
            raise KVError(f"KV refused the command (HTTP {r.status_code})")
        return body.get("result")

    def get_int(self, key: str) -> int:
        v = self._cmd("GET", PREFIX + key)
        return int(v) if v is not None else 0

    def incr(self, key: str, by: int, ttl_s: int) -> int:
        return int(self._cmd("EVAL", INCR_SCRIPT, 1, PREFIX + key, int(by), int(ttl_s)))

    def add_within(self, key: str, by: int, cap: int, ttl_s: int) -> bool:
        res = self._cmd("EVAL", ADD_WITHIN_SCRIPT, 1, PREFIX + key, int(by), int(cap), int(ttl_s))
        return int(res) == 1

    def hget(self, key: str, field: str) -> str | None:
        v = self._cmd("HGET", PREFIX + key, field)
        return None if v is None else str(v)

    def hset(self, key: str, field: str, value: str) -> None:
        self._cmd("HSET", PREFIX + key, field, value)

    def hlen(self, key: str) -> int:
        return int(self._cmd("HLEN", PREFIX + key) or 0)


class SqliteKV:
    """The same store in a local SQLite file, for development and tests. Not for a hosted
    app: Streamlit Community Cloud's disk is wiped on every restart."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS kv_int "
                "(key TEXT PRIMARY KEY, value INTEGER NOT NULL, expires REAL NOT NULL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS kv_hash "
                "(key TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, "
                "PRIMARY KEY (key, field))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10, isolation_level=None)

    def _current(self, con: sqlite3.Connection, key: str) -> int:
        row = con.execute("SELECT value, expires FROM kv_int WHERE key = ?", (key,)).fetchone()
        if row is None or row[1] <= self._clock():
            return 0
        return int(row[0])

    def _write(self, con: sqlite3.Connection, key: str, value: int, ttl_s: int) -> None:
        con.execute(
            "INSERT INTO kv_int (key, value, expires) VALUES (?, ?, ?) ON CONFLICT(key) "
            "DO UPDATE SET value = excluded.value, expires = excluded.expires",
            (key, value, self._clock() + ttl_s),
        )

    def _atomic(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        with self._lock:
            con = self._connect()
            try:
                con.execute("BEGIN IMMEDIATE")  # one writer at a time across processes
                out = fn(con)
                con.execute("COMMIT")
                return out
            except BaseException:
                con.execute("ROLLBACK")
                raise
            finally:
                con.close()

    def get_int(self, key: str) -> int:
        con = self._connect()
        try:
            return self._current(con, key)
        finally:
            con.close()

    def incr(self, key: str, by: int, ttl_s: int) -> int:
        def step(con: sqlite3.Connection) -> int:
            v = self._current(con, key) + int(by)
            self._write(con, key, v, ttl_s)
            return v

        return self._atomic(step)

    def add_within(self, key: str, by: int, cap: int, ttl_s: int) -> bool:
        def step(con: sqlite3.Connection) -> bool:
            v = self._current(con, key)
            if v + by > cap:
                return False
            self._write(con, key, v + int(by), ttl_s)
            return True

        return self._atomic(step)

    def hget(self, key: str, field: str) -> str | None:
        con = self._connect()
        try:
            row = con.execute(
                "SELECT value FROM kv_hash WHERE key = ? AND field = ?", (key, field)
            ).fetchone()
            return None if row is None else str(row[0])
        finally:
            con.close()

    def hset(self, key: str, field: str, value: str) -> None:
        def step(con: sqlite3.Connection) -> None:
            con.execute(
                "INSERT INTO kv_hash (key, field, value) VALUES (?, ?, ?) ON CONFLICT(key, field) "
                "DO UPDATE SET value = excluded.value",
                (key, field, value),
            )

        self._atomic(step)

    def hlen(self, key: str) -> int:
        con = self._connect()
        try:
            row = con.execute("SELECT COUNT(*) FROM kv_hash WHERE key = ?", (key,)).fetchone()
            return int(row[0])
        finally:
            con.close()
