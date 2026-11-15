#!/usr/bin/env python3
"""Fail if publisher page bodies are stored where they must not be (NFR6, B7, gate 9).

Checks:
  1. Files under data/ and results/ (tracked, or untracked but not ignored; .gz files are
     decompressed) contain no HTML document markers and no JSON keys named body, html or
     page_text.
  2. The body cache (~/.cache/citewatch/bodies/, or $CITEWATCH_BODY_CACHE) is empty
     unless node M3.2 (the support check, the only node allowed to hold page text) is
     building.

Usage:
    python scripts/storage_audit.py
    python scripts/storage_audit.py --self-test

Exit 0 when clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import io
import lzma
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

from harness_lib import (
    CATALOG_TSV,
    MAX_UNPACKED,
    ROOT,
    Cap,
    HarnessError,
    git_files,
    load_catalog,
    node_status,
    parse_catalog,
    safe_console,
    unpack,
)

AUDITED_DIRS = ("data", "results")
# "<" may also appear JSON-escaped as \u003c or HTML-escaped as &lt;
LT = rb"(?:<|\\u003c|&lt;|&#0*60;|&#x0*3c;)"
HTML_MARKERS = re.compile(LT + rb"(?:!doctype\s+html|html|body)(?=[\s>/]|\Z)", re.I)
# JSON or repr keys (also double-encoded \"body\":), YAML keys, and CSV/TSV header columns
BODY_KEYS = re.compile(
    # a JSON or repr key, also double-encoded or padded: "body":, \"body\":, " body ":
    rb"(?:\\?[\"']\s*(?:body|html|page_text)\s*\\?[\"']\s*:)"
    # a YAML key, also as a list item: body: / - body:
    rb"|(?:^\s*(?:-\s+)?(?:body|html|page_text)\s*:)",
    re.I | re.M,
)
# A header cell named body/html/page_text, checked only on the first line of a CSV, TSV or
# semicolon file, so prose such as "mind, body, and mood" in stored answers never matches.
HEADER_CELL = re.compile(rb"^\s*\"?(?:body|html|page_text)\"?\s*$", re.I)
TABULAR = (".csv", ".tsv", ".psv")
COMPRESSED = (".gz", ".bz2", ".xz", ".zip")


def header_problem(path: Path, raw: bytes) -> bytes | None:
    """The offending header cell, when the file is tabular and its header names a body column."""
    name = path.name.lower()
    for ext in COMPRESSED:
        name = name.removesuffix(ext)
    if not name.endswith(TABULAR):
        return None
    first = raw.split(b"\n", 1)[0].removeprefix(b"\xef\xbb\xbf").rstrip(b"\r")
    for cell in re.split(rb"[,;\t|]", first):
        if HEADER_CELL.match(cell):
            return cell.strip()
    return None


BODY_NODE = "M3.2"


def body_cache_dir() -> Path:
    env = os.environ.get("CITEWATCH_BODY_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "citewatch" / "bodies"


def audited_files(root: Path) -> list[Path]:
    """Tracked plus untracked-but-not-ignored files under the audited folders."""
    dirs = [d for d in AUDITED_DIRS if (root / d).is_dir()]
    if not dirs:
        return []
    files = git_files(root, *dirs)
    if files is not None:
        return files
    return sorted(p for d in dirs for p in (root / d).rglob("*") if p.is_file())


def file_problems(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    try:
        raw = unpack(path.read_bytes())  # by magic bytes, whatever the file is called
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16 text
            raw = raw.decode("utf-16", "replace").encode("utf-8")
    except (OSError, HarnessError) as exc:
        return [f"{rel}: cannot read ({exc})"]
    problems = []
    m = HTML_MARKERS.search(raw)
    if m:
        problems.append(f"{rel}: HTML document marker {m.group(0).decode('ascii', 'replace')!r}")
    k = BODY_KEYS.search(raw)
    if k:
        problems.append(f"{rel}: page-body key {k.group(0).decode('ascii', 'replace')!r}")
    h = header_problem(path, raw)
    if h:
        problems.append(f"{rel}: page-body column {h.decode('ascii', 'replace')!r} in the header")
    return problems


def cache_problem(cache: Path, caps: list[Cap]) -> str | None:
    if not cache.is_dir() or not any(cache.iterdir()):
        return None
    if node_status(BODY_NODE, caps) == "building":
        return None
    return f"body cache {cache} is not empty and {BODY_NODE} is not building"


def audit(root: Path, cache: Path, caps: list[Cap]) -> list[str]:
    problems = [p for f in audited_files(root) for p in file_problems(f, root)]
    cp = cache_problem(cache, caps)
    return [*problems, cp] if cp else problems


FILLER = b"Compressible filler so the marker cannot survive as plain bytes. " * 200


def _opaque(raw: bytes) -> bytes:
    """A fixture only proves decompression if the marker is absent from the raw bytes."""
    assert not HTML_MARKERS.search(raw) and not BODY_KEYS.search(raw), "fixture leaks its marker"
    return raw


def _zip(content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inner.txt", content)
    return buf.getvalue()


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

        (root / "data" / "broken.gz").write_bytes(b"\x1f\x8bnot really gzip")
        check("an unreadable .gz fails", any("cannot read" in p for p in audit(root, cache, idle)))
        (root / "data" / "broken.gz").unlink()

        sneaky = {
            "UPPER.JSON.GZ": gzip.compress(b'{"Body": "x"}'),
            "renamed.txt": gzip.compress(b"<html>"),
            "double.gz": gzip.compress(gzip.compress(b"<body>")),
            "packed.bz2": bz2.compress(b'{"PAGE_TEXT": 1}'),
            "escaped.json": b'{"x": "\\u003chtml lang=en>"}',
            "entity_lt.txt": b"&lt;body class=x>",
            "entity_dec.txt": b"&#60;html>",
            "entity_hex.txt": b"&#x3C;BODY>",
            "repr.py": b"{'html': 1}",
            "packed.xz": _opaque(lzma.compress(FILLER + b"<html>")),
            "packed.zip": _opaque(_zip(FILLER + b"<body>")),
            "labels.csv": b"citation_ref,verdict,page_text\nv-1,supported,x\n",
            "sheet.tsv": b"ref\tBody\nv-1\tx\n",
            "notes.yaml": b"url: https://x.org\nbody: x\n",
            "list.yaml": b"items:\n  - body: x\n",
            "bom.csv": b"\xef\xbb\xbfbody,url\nx,y\n",
            "spaced.csv": b"ref, body\nv-1, x\n",
            "semi.csv": b"ref;body\nv-1;x\n",
            "utf16.html": "<html>".encode("utf-16"),
            "tail.txt": b"ends with <body",
            "double.json": b'{"rec": "{\\"html\\": 1}"}',
        }
        for name, content in sneaky.items():
            (root / "data" / name).write_bytes(content)
            r = audit(root, cache, idle)
            check(f"{name} fails", any(name in p for p in r))
            (root / "data" / name).unlink()

        cache.mkdir()
        (cache / "page.txt").write_text("page text", encoding="utf-8")
        check(
            "a non-empty body cache fails", any("body cache" in p for p in audit(root, cache, idle))
        )
        check("the body cache is allowed while M3.2 builds", audit(root, cache, busy) == [])
        done = parse_catalog(hdr + "SUP-01\tM3.2\tgreen\t\t\n")
        check(
            "the body cache must be empty once M3.2 is green",
            any("body cache" in p for p in audit(root, cache, done)),
        )
        (cache / "page.txt").unlink()
        bomb = gzip.compress(b" " * (MAX_UNPACKED + 1) + b"<html>")
        (root / "data" / "bomb").write_bytes(bomb)
        check(
            "a decompression bomb fails, never passes",
            any("bomb" in p for p in audit(root, cache, idle)),
        )
        (root / "data" / "bomb").unlink()
        deep = b"<html>"
        for _ in range(4):
            deep = gzip.compress(deep)
        (root / "data" / "deep.gz").write_bytes(deep)
        check("four nested layers fail", any("nested" in p for p in audit(root, cache, idle)))
        (root / "data" / "deep.gz").unlink()
        (root / "data" / "notes.txt").write_bytes(b"BZh is how bzip2 files start")
        check("plain text starting with BZh passes", audit(root, cache, idle) == [])
        (root / "data" / "notes.txt").unlink()
        ordinary = {
            "answer.json.gz": gzip.compress(
                b'{"answer_text": "Exercise is good for your mind, body, and mood; '
                b'CSS, HTML, and JS aside.", "tags": ["head", "body"]}'
            ),
            "quotes.jsonl": b'{"quoted_span": "mind; body; spirit"}\n',
            "labels.csv": b"citation_ref,where_found,verdict\nv-1,body,supported\n",
        }
        for name, content in ordinary.items():
            (root / "data" / name).write_bytes(content)
        r = audit(root, cache, idle)
        check("ordinary text and CSV cells that say 'body' pass", r == [])
        for name in ordinary:
            (root / "data" / name).unlink()
    print("self-test", "PASSED" if failures == 0 else f"FAILED ({failures})")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    safe_console()
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
