#!/usr/bin/env python3
"""Fail if publisher page bodies are stored where they must not be (NFR6, B7, gate 9).

Checks:
  1. Files under data/ and results/ (tracked, or untracked but not ignored; .gz files are
     decompressed) contain no HTML document markers and no JSON keys named body, html or
     page_text.
  2. The body cache (~/.cache/ai-visibility/bodies/, or $VISIBILITY_BODY_CACHE) is empty
     unless node M3.2 (the support check, the only node allowed to hold page text) is
     building.

Usage:
    python scripts/storage_audit.py
    python scripts/storage_audit.py --self-test

Exit 0 when clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from harness_lib import CATALOG_TSV, ROOT, Cap, HarnessError, load_catalog, parse_catalog

AUDITED_DIRS = ("data", "results")
HTML_MARKERS = re.compile(rb"<!doctype\s+html|<html[\s>]|<body[\s>]", re.I)
BODY_KEYS = re.compile(rb'"(?:body|html|page_text)"\s*:')
BODY_NODE = "M3.2"


def body_cache_dir() -> Path:
    env = os.environ.get("VISIBILITY_BODY_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "ai-visibility" / "bodies"


def audited_files(root: Path) -> list[Path]:
    """Tracked plus untracked-but-not-ignored files under the audited folders."""
    dirs = [d for d in AUDITED_DIRS if (root / d).is_dir()]
    if not dirs:
        return []
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", *dirs],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        names = [n for n in out.decode("utf-8").split("\0") if n]
        return sorted(root / n for n in names if (root / n).is_file())
    except (OSError, subprocess.CalledProcessError):
        return sorted(p for d in dirs for p in (root / d).rglob("*") if p.is_file())


def file_problems(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    try:
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        return [f"{rel}: cannot read ({exc})"]
    problems = []
    m = HTML_MARKERS.search(raw)
    if m:
        problems.append(f"{rel}: HTML document marker {m.group(0).decode('ascii', 'replace')!r}")
    k = BODY_KEYS.search(raw)
    if k:
        problems.append(f"{rel}: page-body key {k.group(0).decode('ascii', 'replace')!r}")
    return problems


def cache_problem(cache: Path, caps: list[Cap]) -> str | None:
    if not cache.is_dir() or not any(cache.iterdir()):
        return None
    if any(c.node == BODY_NODE and c.status == "building" for c in caps):
        return None
    return f"body cache {cache} is not empty and {BODY_NODE} is not building"


def audit(root: Path, cache: Path, caps: list[Cap]) -> list[str]:
    problems = [p for f in audited_files(root) for p in file_problems(f, root)]
    cp = cache_problem(cache, caps)
    return [*problems, cp] if cp else problems


def self_test() -> int:
    failures = 0

    def check(name: str, ok: bool) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  [{'ok' if ok else 'WRONG'}] {name}")

    hdr = "cap_id\tnode\tstatus\tproof\tnote\n"
    idle = parse_catalog(hdr + "SUP-01\tM3.2\tnot-started\t\t\n")
    busy = parse_catalog(hdr + "SUP-01\tM3.2\tbuilding\t\t\n")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        cache = Path(tmp) / "cache"
        (root / "data").mkdir(parents=True)
        (root / "results").mkdir()
        (root / "data" / "citations.jsonl").write_text(
            '{"url": "https://www.nhs.uk/", "quoted_span": "Adults should do 150 minutes"}\n',
            encoding="utf-8",
        )
        check("clean metadata passes", audit(root, cache, idle) == [])

        (root / "data" / "page.html").write_text("<!DOCTYPE html><p>x</p>", encoding="utf-8")
        r = audit(root, cache, idle)
        check("an HTML file fails naming it", any("page.html" in p and "HTML" in p for p in r))
        (root / "data" / "page.html").unlink()

        (root / "results" / "meta.json").write_text('{"page_text": "..."}', encoding="utf-8")
        r = audit(root, cache, idle)
        check("a page_text key fails", any("meta.json" in p and "page_text" in p for p in r))
        (root / "results" / "meta.json").unlink()

        (root / "data" / "raw.json.gz").write_bytes(gzip.compress(b'{"html": "<body>x</body>"}'))
        r = audit(root, cache, idle)
        check("a gzipped body fails", any("raw.json.gz" in p for p in r))
        (root / "data" / "raw.json.gz").unlink()

        (root / "data" / "broken.gz").write_bytes(b"not gzip")
        check("an unreadable .gz fails", any("cannot read" in p for p in audit(root, cache, idle)))
        (root / "data" / "broken.gz").unlink()

        cache.mkdir()
        (cache / "page.txt").write_text("page text", encoding="utf-8")
        check(
            "a non-empty body cache fails", any("body cache" in p for p in audit(root, cache, idle))
        )
        check("the body cache is allowed while M3.2 builds", audit(root, cache, busy) == [])
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        caps = load_catalog(CATALOG_TSV)
    except (HarnessError, OSError) as exc:
        print(f"storage audit: cannot read catalog: {exc}")
        return 1
    problems = audit(ROOT, body_cache_dir(), caps)
    for p in problems:
        print(f"storage audit: {p}")
    print(f"storage audit: {'FAIL' if problems else 'OK'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
