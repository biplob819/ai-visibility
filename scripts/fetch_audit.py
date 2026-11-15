#!/usr/bin/env python3
"""Audit fetch logs against the study's politeness rules (Tech Spec §7.2, gate 8).

Each line of a fetch log is one JSON object with the fields in FIELDS. A line whose
outcome is "robots_disallowed" records a URL the fetcher decided not to request; every
other line is a request that was made (even if it then failed).

Rules, each a failure:
  - a line that is not valid JSON or lacks a field;
  - two requests to one host less than 1.0 s apart;
  - a request to a URL whose robots decision was "disallowed";
  - a request for a URL after an earlier request for it returned 401, 403 or 451;
  - more than one distinct user agent across requests.

Usage:
    python scripts/fetch_audit.py                 # every data/**/fetch_log*.jsonl
    python scripts/fetch_audit.py path.jsonl ...
    python scripts/fetch_audit.py --self-test

Exit 0 when every log passes or there are no logs (printed as SKIP); 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from harness_lib import ROOT

FIELDS = ("url", "host", "at", "attempt", "status", "robots", "outcome", "user_agent")
MIN_GAP_S = 1.0
BLOCK_STATUSES = {401, 403, 451}
NO_REQUEST = "robots_disallowed"


def log_files(root: Path) -> list[Path]:
    data = root / "data"
    return sorted(data.rglob("fetch_log*.jsonl")) if data.is_dir() else []


def _parse(lines: Iterable[str], source: str) -> tuple[list[dict], list[str]]:
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
        try:
            at = dt.datetime.fromisoformat(str(row["at"]))
        except ValueError:
            problems.append(f"{where}: bad timestamp {row['at']!r}")
            continue
        if at.tzinfo is None:
            problems.append(f"{where}: timestamp {row['at']!r} has no time zone")
            continue
        row["_at"] = at
        row["_where"] = where
        rows.append(row)
    return rows, problems


def audit(lines: Iterable[str], source: str = "<log>") -> list[str]:
    rows, problems = _parse(lines, source)
    requests = [r for r in rows if r["outcome"] != NO_REQUEST]

    for r in rows:
        if r["robots"] == "disallowed" and r["outcome"] != NO_REQUEST:
            problems.append(f"{r['_where']}: requested {r['url']} although robots disallowed it")

    by_host: dict[str, list[dict]] = defaultdict(list)
    for r in requests:
        by_host[str(r["host"]).lower()].append(r)
    for host, hits in by_host.items():
        hits.sort(key=lambda r: r["_at"])
        for prev, cur in itertools.pairwise(hits):
            gap = (cur["_at"] - prev["_at"]).total_seconds()
            if gap < MIN_GAP_S:
                problems.append(
                    f"{cur['_where']}: host {host} requested twice {gap:.2f} s apart "
                    f"(minimum {MIN_GAP_S:.1f} s)"
                )

    blocked_at: dict[str, dt.datetime] = {}
    for r in sorted(requests, key=lambda r: r["_at"]):
        url = str(r["url"])
        if url in blocked_at and r["_at"] > blocked_at[url]:
            problems.append(f"{r['_where']}: retried {url} after it was blocked")
        if r["status"] in BLOCK_STATUSES and url not in blocked_at:
            blocked_at[url] = r["_at"]

    agents = sorted({str(r["user_agent"]) for r in requests})
    if len(agents) > 1:
        problems.append(f"{source}: {len(agents)} different user agents: {agents}")

    for r in requests:
        if urlsplit(str(r["url"])).hostname not in (None, str(r["host"]).lower()):
            problems.append(f"{r['_where']}: host {r['host']!r} does not match url {r['url']}")
    return problems


def audit_paths(paths: list[Path]) -> list[str]:
    problems: list[str] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{p}: cannot read ({exc})")
            continue
        problems.extend(audit(text.splitlines(), str(p)))
    return problems


def _line(**over: object) -> str:
    row: dict[str, object] = {
        "url": "https://www.nhs.uk/conditions/flu/",
        "host": "www.nhs.uk",
        "at": "2026-11-15T10:00:00+00:00",
        "attempt": 1,
        "status": 200,
        "robots": "allowed",
        "outcome": "ok",
        "user_agent": "AIVisibilityStudy/1.0",
    }
    row.update(over)
    return json.dumps(row)


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
        _line(
            url="https://www.nhs.uk/private/",
            at="2026-11-15T10:00:01.500000+00:00",
            robots="disallowed",
            outcome="robots_disallowed",
            status=None,
        ),
    ]
    check("a polite log passes", audit(good), None)
    check("bad JSON fails", audit(["{nope"]), "not JSON")
    check("a missing field fails", audit(['{"url": "x"}']), "missing")
    check("a naive timestamp fails", audit([_line(at="2026-11-15T10:00:00")]), "no time zone")
    check(
        "two requests 0.5 s apart fail",
        audit([_line(), _line(at="2026-11-15T10:00:00.500000+00:00")]),
        "0.50 s apart",
    )
    check(
        "requesting a disallowed URL fails",
        audit([_line(robots="disallowed")]),
        "although robots disallowed",
    )
    check(
        "retrying after a 403 fails",
        audit([_line(status=403, outcome="blocked"), _line(at="2026-11-15T10:00:05+00:00")]),
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
        (root / "data" / "runs" / "fetch_log_1.jsonl").write_text(
            _line() + "\n" + _line(at="2026-11-15T10:00:00.100000+00:00") + "\n",
            encoding="utf-8",
        )
        check(
            "logs are found under data/ and audited",
            audit_paths(log_files(root)),
            "fetch_log_1.jsonl:2",
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
