#!/usr/bin/env python3
"""Audit fetch logs against the study's politeness rules (Tech Spec §7.2, D-25, gate 8).

Each line of a fetch log is one JSON object with the fields in FIELDS. A line whose
outcome is "robots_disallowed" records a URL the fetcher decided not to request (its status
must be null); every other line is a request that was made, even if it then failed.

All logs are audited together, since the rules hold for the whole study, not per file.
Rules, each a failure:
  - a line that is not valid JSON, repeats a key, lacks a field, or has a field of the wrong
    type or value (a robots_disallowed line must say robots "disallowed" and carry no status
    and no bytes);
  - two requests to one host (case, port and trailing dot ignored) less than 1.0 s apart;
  - a request to a URL whose robots decision was "disallowed" (only a bare /robots.txt is
    exempt);
  - a request for a page after robots refused it, or after a request for it returned 401,
    403 or 451;
  - more than three requests for one page (one try and two retries), counted rather than
    trusted from the logged attempt number;
  - more than one distinct user agent across requests.
Pages are compared with scheme, host case, port, trailing slash, fragment, percent-encoding
and query order normalised, and events are ordered by timestamp, not by file order.

Usage:
    python scripts/fetch_audit.py                 # every data/**/fetch_log*.jsonl[.gz]
    python scripts/fetch_audit.py path.jsonl ...
    python scripts/fetch_audit.py --self-test

Exit 0 when every log passes or there are no logs (printed as SKIP); 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import itertools
import json
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from harness_lib import ROOT, HarnessError, safe_console, unpack

FIELDS = ("url", "host", "at", "attempt", "status", "bytes", "robots", "outcome", "user_agent")
ROBOTS_VALUES = {"allowed", "disallowed"}
MIN_GAP_S = 1.0
BLOCK_STATUSES = {401, 403, 451}
MAX_ATTEMPTS = 3  # one try plus at most two retries (FR5)
NO_REQUEST = "robots_disallowed"
DEFAULT_PORTS = {"http": 80, "https": 443}


def log_files(root: Path) -> list[Path]:
    data = root / "data"
    if not data.is_dir():
        return []
    return sorted({*data.rglob("fetch_log*.jsonl"), *data.rglob("fetch_log*.jsonl.gz")})


def norm_host(host: str) -> str:
    """Lower case, no trailing dot, no port, IPv6 without brackets."""
    h = host.strip().lower()
    if h.startswith("["):
        h = h[1 : h.index("]")] if "]" in h else h[1:]
    elif h.count(":") == 1:
        h = h.split(":", 1)[0]  # host:port
    return h.rstrip(".")


def norm_url(url: str) -> str:
    """Same page, same key: lower-case scheme and host (IPv6 kept in brackets), no default
    port, no fragment, percent-encoding decoded. Raises ValueError on a malformed URL."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = norm_host(parts.hostname or "")
    port = parts.port  # ValueError on a bad port
    shown = f"[{host}]" if ":" in host else host
    netloc = shown if port in (None, DEFAULT_PORTS.get(scheme)) else f"{shown}:{port}"
    return urlunsplit((scheme, netloc, unquote(parts.path) or "/", unquote(parts.query), ""))


def page_key(norm: str) -> str:
    """The retry, robots and attempt rules treat http/https, a trailing slash and the order
    of query parameters as the same page."""
    rest = norm.split("://", 1)[-1]
    path, _, query = rest.partition("?")
    if path.count("/") > 1:
        path = path.rstrip("/")
    return path + ("?" + "&".join(sorted(query.split("&"))) if query else "")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    keys = [k for k, _ in pairs]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise ValueError(f"repeated keys {dupes}")
    return dict(pairs)


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _type_problems(row: dict) -> list[str]:
    problems = []
    for f in ("url", "host", "at", "outcome", "user_agent"):
        if not isinstance(row[f], str) or not row[f].strip():
            problems.append(f"{f} must be a non-empty string")
    if row["robots"] not in ROBOTS_VALUES:
        problems.append(f"robots must be one of {sorted(ROBOTS_VALUES)}, got {row['robots']!r}")
    if not (_is_int(row["attempt"]) and row["attempt"] >= 1):
        problems.append(f"attempt must be an integer >= 1, got {row['attempt']!r}")
    if row["status"] is not None and not (_is_int(row["status"]) and 100 <= row["status"] <= 599):
        problems.append(f"status must be null or an HTTP status code, got {row['status']!r}")
    if row["bytes"] is not None and not (_is_int(row["bytes"]) and row["bytes"] >= 0):
        problems.append(f"bytes must be null or a non-negative integer, got {row['bytes']!r}")
    if row["outcome"] == NO_REQUEST and (row["status"] is not None or row["bytes"] is not None):
        problems.append(f"a {NO_REQUEST} line made no request, so status and bytes must be null")
    if row["outcome"] == NO_REQUEST and row["robots"] != "disallowed":
        problems.append(f'a {NO_REQUEST} line must have robots "disallowed"')
    if _is_int(row["attempt"]) and row["attempt"] > MAX_ATTEMPTS:
        problems.append(f"attempt {row['attempt']} means more than {MAX_ATTEMPTS - 1} retries")
    return problems


def parse(lines: Iterable[str], source: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    problems: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{source}:{lineno}"
        try:
            row = json.loads(line, object_pairs_hook=_no_duplicate_keys)
        except json.JSONDecodeError as exc:
            problems.append(f"{where}: not JSON ({exc.msg})")
            continue
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
            continue
        if not isinstance(row, dict):
            problems.append(f"{where}: not a JSON object")
            continue
        missing = [f for f in FIELDS if f not in row]
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")
            continue
        bad = _type_problems(row)
        if bad:
            problems.extend(f"{where}: {b}" for b in bad)
            continue
        try:
            at = dt.datetime.fromisoformat(row["at"])
        except ValueError:
            problems.append(f"{where}: bad timestamp {row['at']!r}")
            continue
        if at.tzinfo is None:
            problems.append(f"{where}: timestamp {row['at']!r} has no time zone")
            continue
        try:
            row["_url"] = norm_url(row["url"])
        except ValueError as exc:
            problems.append(f"{where}: malformed url {row['url']!r} ({exc})")
            continue
        row["_at"] = at
        row["_where"] = where
        row["_key"] = page_key(row["_url"])
        row["_host"] = norm_host(row["host"])
        rows.append(row)
    return rows, problems


def rules(rows: list[dict], source: str) -> list[str]:
    problems: list[str] = []
    requests = [r for r in rows if r["outcome"] != NO_REQUEST]

    for r in rows:
        if urlsplit(r["_url"]).hostname != r["_host"]:
            problems.append(f"{r['_where']}: host {r['host']!r} does not match url {r['url']}")
        parts = urlsplit(r["_url"])
        is_robots_txt = parts.path == "/robots.txt" and not parts.query
        if r["robots"] == "disallowed" and r["outcome"] != NO_REQUEST and not is_robots_txt:
            problems.append(f"{r['_where']}: requested {r['url']} although robots disallowed it")

    by_host: dict[str, list[dict]] = defaultdict(list)
    for r in requests:
        by_host[r["_host"]].append(r)
    for host, hits in by_host.items():
        hits.sort(key=lambda r: r["_at"])
        for prev, cur in itertools.pairwise(hits):
            gap = (cur["_at"] - prev["_at"]).total_seconds()
            if gap < MIN_GAP_S:
                problems.append(
                    f"{cur['_where']}: host {host} requested twice {gap:.3f} s apart "
                    f"(minimum {MIN_GAP_S:.1f} s; previous at {prev['_where']})"
                )

    blocked: set[str] = set()
    refused: set[str] = set()
    for r in sorted(rows, key=lambda r: r["_at"]):
        if r["outcome"] == NO_REQUEST:
            refused.add(r["_key"])
            continue
        if r["_key"] in refused:
            problems.append(f"{r['_where']}: requested {r['url']} after robots refused it")
        if r["_key"] in blocked:
            problems.append(f"{r['_where']}: retried {r['url']} after it was blocked")
        elif r["status"] in BLOCK_STATUSES:
            blocked.add(r["_key"])

    per_page: dict[str, list[dict]] = defaultdict(list)
    for r in requests:
        per_page[r["_key"]].append(r)
    for hits in per_page.values():
        if len(hits) > MAX_ATTEMPTS:  # the logged attempt number is not trusted on its own
            problems.append(
                f"{hits[-1]['_where']}: {hits[-1]['url']} requested {len(hits)} times "
                f"(at most {MAX_ATTEMPTS}: one try and two retries)"
            )

    agents = sorted({r["user_agent"] for r in requests})
    if len(agents) > 1:
        problems.append(f"{source}: {len(agents)} different user agents: {agents}")
    return problems


def audit(lines: Iterable[str], source: str = "<log>") -> list[str]:
    rows, problems = parse(lines, source)
    return problems + rules(rows, source)


def audit_paths(paths: list[Path]) -> list[str]:
    """Parse every log, then apply the rules to all their lines together."""
    rows: list[dict] = []
    problems: list[str] = []
    for p in paths:
        try:
            text = unpack(p.read_bytes()).decode("utf-8")
        except (OSError, UnicodeDecodeError, HarnessError) as exc:
            problems.append(f"{p}: cannot read ({exc})")
            continue
        r, pr = parse(text.splitlines(), str(p))
        rows.extend(r)
        problems.extend(pr)
    return problems + rules(rows, f"{len(paths)} logs")


def _line(**over: object) -> str:
    row: dict[str, object] = {
        "url": "https://www.nhs.uk/conditions/flu/",
        "host": "www.nhs.uk",
        "at": "2026-11-15T10:00:00+00:00",
        "attempt": 1,
        "status": 200,
        "bytes": 5120,
        "robots": "allowed",
        "outcome": "ok",
        "user_agent": "citewatch/0.1.0 (+https://example.org; study@example.org)",
    }
    row.update(over)
    return json.dumps(row)


SKIPPED = {"robots": "disallowed", "outcome": NO_REQUEST, "status": None, "bytes": None}


def self_test() -> int:
    failures = 0

    def check(name: str, problems: list[str], needle: str | None) -> None:
        nonlocal failures
        ok = (not problems) if needle is None else any(needle in p for p in problems)
        failures += 0 if ok else 1
        print(f"  [{'ok' if ok else 'WRONG'}] {name}")

    good = [
        _line(url="https://www.nhs.uk/robots.txt"),
        _line(at="2026-11-15T10:00:01+00:00"),
        _line(url="https://www.bbc.co.uk/news", host="www.bbc.co.uk"),
        _line(url="https://www.nhs.uk/private/", at="2026-11-15T10:00:01.5+00:00", **SKIPPED),
    ]
    check("a polite log passes", audit(good), None)
    check("bad JSON fails", audit(["{nope"]), "not JSON")
    check("a missing field fails", audit(['{"url": "x"}']), "missing")
    check("a naive timestamp fails", audit([_line(at="2026-11-15T10:00:00")]), "no time zone")
    check("an unknown robots value fails", audit([_line(robots="Disallowed")]), "robots must be")
    check("a string status fails", audit([_line(status="403")]), "status must be")
    check(
        "a skipped line with a status fails",
        audit([_line(**{**SKIPPED, "status": 200})]),
        "status and bytes must be null",
    )
    check(
        "two requests 0.5 s apart fail",
        audit([_line(), _line(at="2026-11-15T10:00:00.5+00:00")]),
        "0.500 s apart",
    )
    check(
        "host case, port and trailing dot share one rate bucket",
        audit(
            [
                _line(),
                _line(
                    url="https://WWW.NHS.UK.:443/x",
                    host="WWW.NHS.UK.",
                    at="2026-11-15T10:00:00.2+00:00",
                ),
            ]
        ),
        "0.200 s apart",
    )
    check(
        "requesting a disallowed URL fails",
        audit([_line(robots="disallowed")]),
        "although robots disallowed",
    )
    check(
        "robots.txt itself is exempt from the robots rule",
        audit([_line(url="https://www.nhs.uk/robots.txt", robots="disallowed")]),
        None,
    )
    check(
        "retrying after a 403 fails, whatever the URL form",
        audit(
            [
                _line(status=403, outcome="blocked"),
                _line(
                    url="https://WWW.nhs.uk:443/conditions/flu/#x", at="2026-11-15T10:00:05+00:00"
                ),
            ]
        ),
        "after it was blocked",
    )
    check(
        "retrying after a 401 fails",
        audit([_line(status=401, outcome="blocked"), _line(at="2026-11-15T10:00:05+00:00")]),
        "after it was blocked",
    )
    check(
        "retrying over http after an https 451 fails",
        audit(
            [
                _line(status=451, outcome="blocked"),
                _line(url="http://www.nhs.uk/conditions/flu/", at="2026-11-15T10:00:05+00:00"),
            ]
        ),
        "after it was blocked",
    )
    check(
        "requesting a URL robots refused earlier fails",
        audit([_line(**SKIPPED), _line(at="2026-11-15T10:00:05+00:00")]),
        "after robots refused it",
    )
    check(
        "a skipped line with bytes fails",
        audit([_line(**{**SKIPPED, "bytes": 512})]),
        "status and bytes must be null",
    )
    check("a fourth attempt fails", audit([_line(attempt=4)]), "more than 2 retries")
    check(
        "IPv6 hosts are handled",
        audit([_line(url="https://[2001:db8::1]/a", host="[2001:db8::1]")]),
        None,
    )
    check("a malformed url fails", audit([_line(url="https://[::1/x")]), "malformed url")
    check("a repeated key fails", audit([_line()[:-1] + ', "robots": "allowed"}']), "repeated keys")
    check(
        "a skipped line must say robots disallowed",
        audit([_line(**{**SKIPPED, "robots": "allowed"})]),
        'must have robots "disallowed"',
    )
    check(
        "bytes 0 on a skipped line fails", audit([_line(**{**SKIPPED, "bytes": 0})]), "must be null"
    )
    check(
        "robots.txt with a query is not exempt",
        audit([_line(url="https://www.nhs.uk/robots.txt?x=1", robots="disallowed")]),
        "although robots disallowed",
    )
    check("a status outside 100-599 fails", audit([_line(status=999)]), "status must be")
    check("an unparseable timestamp fails", audit([_line(at="yesterday")]), "bad timestamp")
    check(
        "events are ordered by time, not by file order",
        audit([_line(at="2026-11-15T10:00:09+00:00"), _line(status=403, outcome="blocked")]),
        "after it was blocked",
    )
    check(
        "percent-encoding does not hide a retry",
        audit(
            [
                _line(url="https://www.nhs.uk/a%20b", status=403, outcome="blocked"),
                _line(url="https://www.nhs.uk/a b", at="2026-11-15T10:00:09+00:00"),
            ]
        ),
        "after it was blocked",
    )
    check(
        "four requests for one page fail even if each says attempt 1",
        audit([_line(at=f"2026-11-15T10:00:0{i}+00:00") for i in range(0, 8, 2)]),
        "requested 4 times",
    )
    check("a host field with a port passes", audit([_line(host="www.nhs.uk:443")]), None)
    check("a non-string url fails", audit([_line(url=42)]), "url must be")
    check("a boolean attempt fails", audit([_line(attempt=True)]), "attempt must be")
    check(
        "retrying with a trailing slash or reordered query fails",
        audit(
            [
                _line(url="https://a.org/p?x=1&y=2", host="a.org", status=403, outcome="blocked"),
                _line(url="https://a.org/p/?y=2&x=1", host="a.org", at="2026-11-15T10:00:05+00:00"),
            ]
        ),
        "after it was blocked",
    )
    check(
        "two user agents fail",
        audit([_line(), _line(host="a.com", url="https://a.com/", user_agent="Other/1.0")]),
        "different user agents",
    )
    check(
        "a host that does not match the url fails",
        audit([_line(host="www.bbc.co.uk")]),
        "does not match",
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        check("no data folder means no logs", [] if not log_files(root) else ["found"], None)
        (root / "data" / "runs").mkdir(parents=True)
        (root / "data" / "runs" / "fetch_log_1.jsonl").write_text(_line() + "\n", encoding="utf-8")
        (root / "data" / "runs" / "fetch_log_2.jsonl.gz").write_bytes(
            gzip.compress((_line(at="2026-11-15T10:00:00.1+00:00") + "\n").encode())
        )
        check(
            "rules apply across files, gzipped logs included",
            audit_paths(log_files(root)),
            "0.100 s apart",
        )
        bad = root / "data" / "runs" / "fetch_log_3.jsonl"
        bad.write_bytes(b"\xff\xfe not utf-8")
        check("an unreadable log fails, never drops out", audit_paths([bad]), "cannot read")
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    safe_console()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    paths = args.paths or log_files(ROOT)
    if not paths:
        print("fetch audit: SKIP (no fetch logs yet)")
        return 0
    problems = audit_paths(paths)
    for p in problems:
        print(f"fetch audit: {p}")
    print(f"fetch audit: {'FAIL' if problems else 'OK'} ({len(paths)} logs)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
