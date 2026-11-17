"""REL-02: audit every file version in the repository's history (OWNER D-21: public since the
first push).

    uv run python scripts/history_audit.py            # exit 1 on any finding
    uv run python scripts/history_audit.py --json

Checks every blob reachable from any ref, at every path it was committed under:
- secrets: the same patterns as scripts/secret_scan.py (and its allow marker);
- `.env` files: no path named `.env` or `.env.*` was ever committed (`.env.example` excepted);
- page bodies: blobs under the audited study folders hold no HTML document or page-body key
  (scripts/storage_audit.py's rules);
- job-search content (OWNER D-22): none of the private notes' markers, outside the files that
  state the rule itself.
Run it on a full clone; a shallow clone audits only the history it has (it says how much).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import secret_scan
import storage_audit
from harness_lib import HarnessError, unpack

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = re.compile(r"(^|/)\.env(\.(?!example$)[^/]*)?$")
JOB_MARKERS = ("greenhouse.io", "job hunt", "signals & data products", "cover letter")
# files that state the D-22 rule or test for its markers; they name the markers, nothing more
RULE_FILES = ("docs/decisions.md", "AI Visibility Tech Spec.md", "AI Visibility PRD.md")


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def blobs() -> dict[str, set[str]]:
    """blob sha -> every path it was committed under, across all refs."""
    out: dict[str, set[str]] = defaultdict(set)
    for line in _git("rev-list", "--all", "--objects").decode().splitlines():
        sha, _, path = line.partition(" ")
        if path:
            out[sha].add(path)
    return out


def _is_blob(shas: list[str]) -> set[str]:
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=ROOT,
        input="\n".join(shas).encode(),
        capture_output=True,
        check=True,
    )
    return {line.split()[0] for line in proc.stdout.decode().splitlines() if line.endswith(" blob")}


def _audited(path: str) -> bool:
    return path.split("/")[0] in storage_audit.AUDITED_DIRS or (
        path.startswith("studies/") and ("/data/" in path or "/results/" in path)
    )


def findings() -> tuple[list[str], dict[str, int]]:
    objs = blobs()
    shas = sorted(_is_blob(list(objs)))
    problems: list[str] = []
    for paths in objs.values():
        for p in sorted(paths):
            if ENV_PATH.search(p):
                problems.append(f"{p}: a .env file was committed")
    for sha in shas:
        paths = sorted(objs[sha])
        raw = _git("cat-file", "blob", sha)
        try:
            data = unpack(raw)
        except HarnessError:
            data = raw
        text = data.decode("utf-8", errors="replace")
        where = f"{paths[0]} ({sha[:10]})"
        for lineno, line in enumerate(text.splitlines(), start=1):
            if secret_scan.ALLOW in line:
                continue
            for name, pat in secret_scan.PATTERNS.items():
                m = pat.search(line)
                if m and (name != "openai key" or secret_scan._looks_random(m.group(0))):
                    problems.append(f"{where}:{lineno}: possible {name}")
        if any(_audited(p) for p in paths):
            if storage_audit.HTML_MARKERS.search(data):
                problems.append(f"{where}: HTML document marker in study data")
            if storage_audit.BODY_KEYS.search(data):
                problems.append(f"{where}: page-body key in study data")
        if not any(p in RULE_FILES or p.startswith(("tests/", "scripts/")) for p in paths):
            low = text.lower()
            for marker in JOB_MARKERS:
                if marker in low:
                    problems.append(f"{where}: job-search marker {marker!r} (OWNER D-22)")
    shallow = (ROOT / ".git" / "shallow").is_file()
    stats = {
        "commits": len(_git("rev-list", "--all").splitlines()),
        "blobs": len(shas),
        "shallow": int(shallow),
    }
    return problems, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    problems, stats = findings()
    if a.json:
        print(json.dumps({"ok": not problems, "problems": problems, **stats}, indent=1))
    else:
        print(
            f"history audit: {stats['commits']} commits, {stats['blobs']} file versions"
            + (" (shallow clone: partial history)" if stats["shallow"] else "")
        )
        for p in problems:
            print(f"  {p}")
        print("OK" if not problems else f"{len(problems)} finding(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
