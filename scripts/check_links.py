"""OSS-09: every link in the README, the docs and the case study resolves.

    uv run python scripts/check_links.py            # local files only (offline)
    uv run python scripts/check_links.py --online   # also fetch every http(s) link (HEAD, then GET)

Exit 1 lists each broken link with the file that holds it.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "README.md",
    "DATA_CARD.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "docs").glob("*.md")),
]
LINK = re.compile(r"\]\(([^)\s]+)\)")
UA = "citewatch-link-check (+https://github.com/biplob819/ai-visibility)"


def links() -> list[tuple[str, str]]:
    out = []
    for f in FILES:
        path = ROOT / f
        if path.is_file():
            text = re.sub(r"```.*?```|`[^`\n]*`", "", path.read_text(encoding="utf-8"), flags=re.S)
            out += [(f, u) for u in LINK.findall(text)]  # code spans are examples, not links
    return out


def local_problem(src: str, url: str) -> str | None:
    if url.startswith(("http://", "https://", "mailto:", "#")):
        return None
    target = (ROOT / Path(src).parent / unquote(url.split("#")[0])).resolve()
    return None if target.exists() else f"{src}: {url} (no such file)"


def online_problem(src: str, url: str) -> str | None:
    last: Exception | None = None
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status < 400:
                    return None
        except Exception as exc:
            last = exc
    return f"{src}: {url} ({last})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true")
    a = ap.parse_args(argv)
    found = links()
    problems = [p for s, u in found if (p := local_problem(s, u))]
    if a.online:
        seen: set[str] = set()
        for s, u in found:
            if u.startswith(("http://", "https://")) and u not in seen:
                seen.add(u)
                if p := online_problem(s, u):
                    problems.append(p)
    print(f"{len(found)} links checked" + (" (online)" if a.online else " (local)"))
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
