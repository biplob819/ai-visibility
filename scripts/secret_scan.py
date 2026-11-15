#!/usr/bin/env python3
"""Fail if anything that looks like an API key is in the repo.

Scans tracked and untracked (not ignored) files. Lines containing the marker
`secret-scan: allow` are skipped (for documented fake examples only).

Known limit: a key split across string literals ("sk-ant-" "abc...") is not detected.
Provider-side secret scanning on GitHub is the backstop for that case.

Usage:
    python scripts/secret_scan.py [paths...]
    python scripts/secret_scan.py --self-test
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from harness_lib import ROOT, HarnessError, git_files, safe_console, unpack

PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai key": re.compile(
        r"(?<![A-Za-z0-9])sk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}"
    ),
    "aws access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws secret key": re.compile(
        r"(?i)aws_?secret_?(?:access_?)?key\W{0,4}[=:]\W{0,4}[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])"
    ),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "github fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}"),
    "pypi token": re.compile(r"\bpypi-[A-Za-z0-9_\-]{50,}"),
    "private key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?-----"
    ),
}
ALLOW = "secret-scan: allow"


def candidate_files(root: Path) -> list[Path]:
    files = git_files(root)
    if files is not None:
        return files
    skip = {".git", ".venv", "node_modules", "__pycache__", "dist"}
    return [p for p in root.rglob("*") if p.is_file() and not (skip & set(p.parts))]


def _looks_random(token: str) -> bool:
    """Real OpenAI keys mix upper case and digits; URL slugs like sk-ii-facial-essence don't."""
    body = token.split("-", 1)[-1]
    return any(c.isupper() for c in body) and any(c.isdigit() for c in body)


def scan(files: list[Path]) -> list[str]:
    hits: list[str] = []
    for f in files:
        if not f.is_file():  # every file is scanned: a suffix proves nothing
            continue
        try:
            # never skip a file for its encoding: undecodable bytes become U+FFFD
            text = unpack(f.read_bytes()).decode("utf-8", errors="replace")
        except HarnessError as exc:
            hits.append(f"{f}: cannot unpack to scan ({exc})")
            continue
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW in line:
                continue
            for name, pat in PATTERNS.items():
                m = pat.search(line)
                if m and (name != "openai key" or _looks_random(m.group(0))):
                    hits.append(f"{f}:{lineno}: possible {name}")
    return hits


def self_test() -> int:
    fake_ant = "sk-ant-" + "a1B2" * 10
    fake_oai = "sk-proj-" + "Z9y8" * 10
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "leak.py"
        bad.write_text(f'KEY = "{fake_ant}"\nOTHER = "{fake_oai}"\n', encoding="utf-8")
        allowed = Path(tmp) / "doc.md"
        allowed.write_text(f"example: {fake_ant}  # {ALLOW}\n", encoding="utf-8")
        clean = Path(tmp) / "clean.py"
        clean.write_text('KEY = os.environ["ANTHROPIC_API_KEY"]\n', encoding="utf-8")
        checks = [
            ("detects leaked keys", len(scan([bad])) == 2),
            ("honours allow marker", scan([allowed]) == []),
            ("clean file passes", scan([clean]) == []),
        ]
        import gzip as _gz
        import subprocess as _sp

        packed = Path(tmp) / "dump.bin"
        packed.write_bytes(_gz.compress(_gz.compress(f"k={fake_ant}\n".encode())))
        checks.append(("detects a key inside a double-gzipped file", len(scan([packed])) == 1))
        under = Path(tmp) / "env.py"
        under.write_text(f"X_{fake_oai}\n", encoding="utf-8")
        checks.append(("detects an OpenAI key after an underscore", len(scan([under])) == 1))
        slug = Path(tmp) / "citations.jsonl"
        slug.write_text(
            '{"url": "https://x.org/what-is-sk-ii-facial-treatment-essence-and-how-to-use-it"}\n',
            encoding="utf-8",
        )
        checks.append(("a URL slug starting sk- is not a key", scan([slug]) == []))
        corrupt = Path(tmp) / "broken.gz"
        corrupt.write_bytes(b"\x1f\x8b corrupt")
        checks.append(
            (
                "a corrupt archive is reported, not skipped",
                any("cannot unpack" in h for h in scan([corrupt])),
            )
        )
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _sp.run(["git", "init", "-q"], cwd=repo, check=True)
        (repo / "notes café ü.md").write_text(f"K = {fake_ant}\n", encoding="utf-8")
        checks.append(
            ("scans files whose names git would quote", len(scan(candidate_files(repo))) == 1)
        )
    for name, ok in checks:
        failures += 0 if ok else 1
        print(f"  [{'ok' if ok else 'WRONG'}] {name}")
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
    files = args.paths or candidate_files(ROOT)
    hits = scan(files)
    if hits:
        print("secret scan: FAIL")
        for h in hits:
            print(f"  - {h}")
        return 1
    print(f"secret scan: OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
