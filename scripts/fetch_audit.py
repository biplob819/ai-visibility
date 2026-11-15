#!/usr/bin/env python3
"""Audit fetch logs against the study's politeness rules (Tech Spec §7.2, D-25, gate 8).

Each line of a fetch log is one JSON object with the fields in FIELDS. A line whose
outcome is "robots_disallowed" records a URL the fetcher decided not to request (its status
must be null); every other line is a request that was made, even if it then failed.

All logs are audited together, since the rules hold for the whole study, not per file.
Rules, each a failure:
  - a line that is not valid JSON, lacks a field, or has a field of the wrong type or value;
  - two requests to one host (case, port and trailing dot ignored) less than 1.0 s apart;
  - a request to a URL whose robots decision was "disallowed" (robots.txt itself exempt);
  - a request for a URL after an earlier request for it returned 401, 403 or 451, comparing
    URLs with host case, default port and fragment normalised;
  - more than one distinct user agent across requests.

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
from urllib.parse import urlsplit, urlunsplit

from harness_lib import ROOT, HarnessError, unpack

FIELDS = ("url", "host", "at", "attempt", "status", "bytes", "robots", "outcome", "user_agent")
ROBOTS_VALUES = {"allowed", "disallowed"}
MIN_GAP_S = 1.0
BLOCK_STATUSES = {401, 403, 451}
NO_REQUEST = "robots_disallowed"
DEFAULT_PORTS = {"http": 80, "https": 443}


def log_files(root: Path) -> list[Path]:
    data = root / "data"
    if not data.is_dir():
        return []
    return sorted({*data.rglob("fetch_log*.jsonl"), *data.rglob("fetch_log*.jsonl.gz")})


def norm_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def norm_url(url: str) -> str:
    """Same page, same key: lower-case scheme and host, no default port, no fragment."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = norm_host(parts.hostname or "")
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host if port in (None, DEFAULT_PORTS.get(scheme)) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


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
        problems.append(f"attempt must be an integer ≥ 1, got {row['attempt']!r}")
    if row["status"] is not None and not (_is_int(row["status"]) and 100 <= row["status"] <= 599):
        problems.append(f"status must be null or an HTTP status code, got {row['status']!r}")
    if row["bytes"] is not None and not (_is_int(row["bytes"]) and row["bytes"] >= 0):
        problems.append(f"bytes must be null or a non-negative integer, got {row['bytes']!r}")
    if row["outcome"] == NO_REQUEST and row["status"] is not None:
        problems.append(f"a {NO_REQUEST} line made no request, so its status must be null")
    return problems


def parse(lines: Iterable[str], source: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    problems: list[str] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{source}:{lineno}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"{where}: not JSON ({exc.msg})")
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
        row["_at"] = at
        row["_where"] = where
        row["_url"] = norm_url(row["url"])
        row["_host"] = norm_host(row["host"])
        rows.append(row)
    return rows, problems


def rules(rows: list[dict], source: str) -> list[str]:
    problems: list[str] = []
    requests = [r for r in rows if r["outcome"] != NO_REQUEST]

    for r in rows:
        if urlsplit(r["_url"]).hostname != r["_host"]:
            problems.append(f"{r['_where']}: host {r['host']!r} does not match url {r['url']}")
        is_robots_txt = urlsplit(r["_url"]).path == "/robots.txt"
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

    blocked_at: dict[str, dt.datetime] = {}
    for r in sorted(requests, key=lambda r: r["_at"]):
        if r["_url"] in blocked_at:
            problems.append(f"{r['_where']}: retried {r['url']} after it was blocked")
        elif r["status"] in BLOCK_STATUSES:
            blocked_at[r["_url"]] = r["_at"]

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
        "status must be null",
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
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
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
