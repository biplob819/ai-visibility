"""REL-02: audit every file version and every message in the repository's history (OWNER D-21:
public since the first push).

    uv run python scripts/history_audit.py            # exit 1 on any finding
    uv run python scripts/history_audit.py --json

Checks every blob reachable from any ref, at every path it was committed under, plus every commit
message, annotated-tag message and author/committer/tagger identity:
- secrets: scripts/secret_scan.py's patterns (and its allow marker), on every line;
- secret-bearing paths: `.env`, `.env.*` (`.env.example` excepted), `*.env`, `.envrc`,
  `.streamlit/secrets.toml`, `*.pem`, `id_rsa*`;
- page bodies: blobs under the study folders hold no HTML marker, no page-body key and no long
  text/content/main_text value (scripts/storage_audit.py's rules); anywhere else, no full HTML
  page (an HTML document over PAGE_MAX bytes, or a <body> with more than BODY_TEXT_MAX characters
  of visible text). ALLOWED_PAGES names the only exceptions;
- job-search content (OWNER D-22): no JOB_MARKERS on any line of any file or message, except the
  exact lines in LINE_ALLOW (the lines that state the D-22 rule or list the markers);
- private owner links (docs.google.com, notion.so, claude.ai artifacts): reported as low findings
  that do not fail the audit; KNOWN_PRIVATE_LINKS lists the ones already reviewed.
Run it on a full clone; a shallow clone audits only the history it has (it says how much).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
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
ENV_PATH = re.compile(
    r"(?:^|/)(?:\.env(?:\.(?!example$)[^/]*)?|[^/]+\.env|\.envrc|\.streamlit/secrets\.toml"
    r"|[^/]+\.pem|id_rsa[^/]*)$"
)

# OWNER D-22: markers of the private job-search notes. Matched case-insensitively at the start of
# a word, so plurals count too.
JOB_MARKERS = (
    "greenhouse.io",
    "job hunt",
    "signals & data products",
    "cover letter",
    "hiring manager",
    "linkedin.com/in",
    "recruiter",
    "job application",
    "outreach tracker",
)
# "referral" alone is everyday NHS language in the study data (a GP referral, self-referral), so
# only its job-search phrasings count.
JOB_PHRASES = (
    r"(?:employee|job|internal|warm) referrals?",
    r"referrals? (?:ask|note|message|email|dm|bonus|intro)",
)
_JOB_RE = re.compile(
    "|".join(
        [
            *(rf"(?<![a-z0-9]){re.escape(m)}" for m in JOB_MARKERS),
            *(rf"(?<![a-z0-9]){p}" for p in JOB_PHRASES),
        ]
    ),
    re.I,
)

# Exact lines that may carry a job marker: (path, sha256 of the stripped line, first 16 hex) ->
# why. Each entry states the D-22 rule or lists the markers; a new line, or an edited one, in the
# same file is still caught. Commit messages use the path "commit:<full sha>".
LINE_ALLOW: dict[tuple[str, str], str] = {
    # this file's JOB_MARKERS tuple, one entry per marker line
    ("scripts/history_audit.py", "f1ced50fcebc2c76"): "JOB_MARKERS entry 1",
    ("scripts/history_audit.py", "dbd34dccbc7717c8"): "JOB_MARKERS entry 2",
    ("scripts/history_audit.py", "94665b1e8ff0aeeb"): "JOB_MARKERS entry 3",
    ("scripts/history_audit.py", "b4e9ea667fc64066"): "JOB_MARKERS entry 4",
    ("scripts/history_audit.py", "807ddeccacaaac7d"): "JOB_MARKERS entry 5",
    ("scripts/history_audit.py", "ad278c48ce920c9e"): "JOB_MARKERS entry 6",
    ("scripts/history_audit.py", "a50655b8ef4dd7c7"): "JOB_MARKERS entry 7",
    ("scripts/history_audit.py", "16b90a2bdf61df59"): "JOB_MARKERS entry 8",
    ("scripts/history_audit.py", "54d6bf80fac26a98"): "JOB_MARKERS entry 9",
    (
        "scripts/history_audit.py",
        "3e4696912ff0436d",
    ): "JOB_MARKERS tuple as first committed (23c322b)",
    ("tests/harness/test_history_audit.py", "f2b96a7d8afc6ec1"): "planted case, 23c322b",
    ("tests/harness/test_history_audit.py", "3e1c834b962c324a"): "its assertion, 23c322b",
    ("tests/harness/test_records.py", "460c5c1fef8e123e"): "the markers the D-22 test forbids",
    # a third-party robots.txt (UCL) cached by the fetch stage lists a careers sitemap URL
    (
        "studies/uk-health/data/raw/robots/24/"
        "24f4a91a0854c0a956b2ec4ce5796a64feb9daf1d76b3db5cb917ed89dc5a4ab.json.gz",
        "5649598305bf8303",
    ): "third-party robots.txt in study data",
}

# Private owner pages (not public, but a link reveals the owner's workspace). Reported, never
# failing. KNOWN_PRIVATE_LINKS are the review-page links already in history (old RUN-STATE
# versions linked each node's review artifact); they are listed so a new link stands out.
_PRIVATE_RE = re.compile(
    r"(?:https?://)?(?:docs\.google\.com/|(?:[\w-]+\.)?notion\.so/|claude\.ai/(?:code/)?artifacts?/)"
    r"[^\s)\]>\"'`|]+",
    re.I,
)
KNOWN_PRIVATE_LINKS: dict[str, str] = {
    "https://claude.ai/artifact/LKga9AEnuwUJvfAw3ipqmY": "N1.4 RUN-STATE: question review page",
    "https://claude.ai/artifact/7EYYRK8LLBiwXHVgdjD7YR": "A2.3 RUN-STATE: date-label review page",
    "https://claude.ai/artifact/HQwemfBkBqyGWHhZYuwK3s": "M3.2 RUN-STATE: blind-label page",
    "https://claude.ai/artifact/98WCVLR4agDWTjdhzHioSV": "M3.3 RUN-STATE: blind-label page",
}

# Full HTML pages allowed outside the study folders: (path glob, max bytes, why).
ALLOWED_PAGES = (
    ("tests/fixtures/dates/pages/*.html", 4096, "reduced date-extraction fixtures (B7 allows)"),
    ("docs/signal-spec.html", 65536, "generated project page"),
    (
        "scripts/build_signal_spec.py",
        32768,
        "the generator of docs/signal-spec.html (its template)",
    ),
    ("src/citewatch/report/dashboard.py", 65536, "the dashboard generator (its page template)"),
    ("src/citewatch/report/post.py", 32768, "the post generator (its page template)"),
)
PAGE_MAX = 20_000  # an HTML document bigger than this is a stored page
BODY_TEXT_MAX = 2_000  # visible characters inside one <body>...</body>
_DOC_START = re.compile(r"\A\s*(?:<\?xml[^>]*>\s*)?<(?:!doctype\s+html|html)\b", re.I)
_BODY = re.compile(r"<body\b[^>]*>((?:(?!<body\b).){0,400000}?)</body", re.I | re.S)
# a page cut off before </body> (B4.4 pass 2): the body runs to the end of the blob; source code
# that merely builds pages (.py) is judged by the closed form only
_OPEN_BODY = re.compile(r"<body\b[^>]*>((?:(?!</body).){0,400000})\Z", re.I | re.S)
_NOISE = re.compile(r"<(script|style)\b.*?</\1\s*>|<[^>]*>", re.I | re.S)
_UNESCAPE = (("\\u003c", "<"), ("\\u003e", ">"), ("&lt;", "<"), ("&gt;", ">"), ('\\"', '"'))


def _git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, input=data
    ).stdout


def blobs() -> dict[str, set[str]]:
    """blob sha -> every path it was committed under, across all refs. `rev-list --objects`
    names a blob once, under one path, so identical files at several paths would hide all but
    one; the raw log of every commit (merges against each parent, root commits included) names
    each (blob, path) pair."""
    out: dict[str, set[str]] = defaultdict(set)
    raw = _git(
        "log", "--all", "--no-renames", "--raw", "--no-abbrev", "-m", "--root", "-z", "--format="
    )
    fields = raw.split(b"\0")
    i = 0
    while i < len(fields):
        meta = fields[i].lstrip(b"\n")
        if not meta.startswith(b":"):
            i += 1
            continue
        parts = meta.split()
        new_sha, path = parts[3].decode(), fields[i + 1].decode("utf-8", "replace")
        if parts[1] != b"160000" and set(new_sha) != {"0"}:  # skip submodules and deletions
            out[new_sha].add(path)
        i += 2
    return out


def _contents(shas: list[str]) -> dict[str, bytes]:
    """Every blob's bytes in one `git cat-file --batch` call (non-blobs are left out)."""
    raw = _git("cat-file", "--batch", data="\n".join(shas).encode() + b"\n")
    out: dict[str, bytes] = {}
    i = 0
    while i < len(raw):
        nl = raw.index(b"\n", i)
        head = raw[i:nl].split()
        if len(head) < 3:  # "<sha> missing"
            i = nl + 1
            continue
        size = int(head[2])
        if head[1] == b"blob":
            out[head[0].decode()] = raw[nl + 1 : nl + 1 + size]
        i = nl + 1 + size + 1
    return out


def line_key(line: str) -> str:
    return hashlib.sha256(line.strip().encode()).hexdigest()[:16]


def _glob(path: str, pattern: str) -> bool:
    """A glob whose `*` never crosses a folder: same depth, each part matched on its own."""
    a, b = path.split("/"), pattern.split("/")
    return len(a) == len(b) and all(fnmatch.fnmatchcase(x, y) for x, y in zip(a, b, strict=True))


def _allowed_page(path: str, size: int) -> bool:
    return any(_glob(path, g) and size <= cap for g, cap, _ in ALLOWED_PAGES)


def page_problem(path: str, data: bytes) -> str | None:
    """Why this blob, committed at `path`, looks like a stored web page, or None."""
    text = data.decode("utf-8", "replace")
    for a, b in _UNESCAPE:
        text = text.replace(a, b)
    if "<" not in text or not re.search(r"<(?:html|body|!doctype)", text, re.I):
        return None
    if _allowed_page(path, len(data)):
        return None
    doc = bool(_DOC_START.search(text)) or path.lower().endswith((".html", ".htm", ".xhtml"))
    if doc and len(data) > PAGE_MAX:
        return f"an HTML document of {len(data)} bytes (a stored page?)"
    if path.endswith(".py"):
        # Python sources that build or test pages carry page markup as string literals, so
        # their body text is not judged; but a large source carrying a whole document is
        # (B4.4 pass 4): the generators are allow-listed above with size caps
        if len(data) > PAGE_MAX and re.search(r"<!doctype\s+html|<html\b", text, re.I):
            return f"a {len(data)}-byte Python source carrying an HTML document (a stored page?)"
        return None
    bodies = [m.group(1) for m in _BODY.finditer(text)]
    head = text.lstrip("\ufeff \t\r\n")
    starts_as_page = re.match(r"(?:<\?xml[^>]*>\s*)?<(?:!doctype\s+html|html)\b", head, re.I)
    if not bodies and starts_as_page:
        bodies = [m.group(1) for m in _OPEN_BODY.finditer(text)]
    for body in bodies:
        visible = " ".join(_NOISE.sub(" ", body).split())
        if len(visible) > BODY_TEXT_MAX:
            return f"a <body> with {len(visible)} characters of text (a stored page?)"
    return None


def _audited(path: str) -> bool:
    return path.split("/")[0] in storage_audit.AUDITED_DIRS or (
        path.startswith("studies/") and ("/data/" in path or "/results/" in path)
    )


class Report:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.private: list[str] = []
        self.known_private = 0
        self.stats: dict[str, int] = {}

    def text(self, where: str, paths: list[str], text: str) -> None:
        """Secret, job-marker and private-link checks on every line."""
        secrets = any(p.search(text) for p in secret_scan.PATTERNS.values())
        jobs = bool(_JOB_RE.search(text))
        links = bool(_PRIVATE_RE.search(text))
        if not (secrets or jobs or links):  # whole-text prefilter: most blobs stop here
            return
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name in secret_scan.line_hits(line) if secrets else ():
                self.problems.append(f"{where}:{lineno}: possible {name}")
            m = _JOB_RE.search(line) if jobs else None
            if m and not any((p, line_key(line)) in LINE_ALLOW for p in paths):
                self.problems.append(
                    f"{where}:{lineno}: job-search marker {m.group(0).lower()!r} "
                    f"(OWNER D-22) [line {line_key(line)}]"
                )
            for link in _PRIVATE_RE.findall(line) if links else ():
                link = link.rstrip(".,;:")
                if link in KNOWN_PRIVATE_LINKS:
                    self.known_private += 1
                else:
                    self.private.append(f"{where}:{lineno}: private link {link}")


def _messages(rep: Report) -> int:
    log = _git("log", "--all", "--format=%H%x00%an <%ae>%x00%cn <%ce>%x00%B%x1e").decode(
        "utf-8", "replace"
    )
    n = 0
    for rec in log.split("\x1e"):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        sha, author, committer, body = rec.split("\x00", 3)
        n += 1
        key = [f"commit:{sha}"]
        rep.text(f"commit {sha[:10]} message", key, body)
        rep.text(f"commit {sha[:10]} identity", key, f"{author}\n{committer}")
    tags = _git(
        "for-each-ref",
        "refs/tags",
        "--format=%(refname:short)%00%(objecttype)%00%(taggername) %(taggeremail)%00%(contents)%1e",
    ).decode("utf-8", "replace")
    for rec in tags.split("\x1e"):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        name, kind, tagger, body = rec.split("\x00", 3)
        if kind == "tag":
            rep.text(f"tag {name} message", [f"tag:{name}"], f"{body}\n{tagger}")
    return n


def findings() -> tuple[list[str], dict[str, int]]:
    """(failing problems, stats); report() also gives the private links."""
    rep = report()
    return rep.problems, rep.stats


def report() -> Report:
    objs = blobs()
    contents = _contents(sorted(objs))
    rep = Report()
    for paths in objs.values():
        for p in sorted(paths):
            if ENV_PATH.search(p):
                rep.problems.append(
                    f"{p}: a secret-bearing file (.env, key, secrets) was committed"
                )
    for sha in sorted(contents):
        paths = sorted(objs[sha])
        raw = contents[sha]
        where = f"{paths[0]} ({sha[:10]})"
        try:
            data = unpack(raw)
        except HarnessError as exc:
            rep.problems.append(f"{where}: cannot unpack to audit ({exc})")
            data = raw
        rep.text(where, paths, data.decode("utf-8", errors="replace"))
        if any(_audited(p) for p in paths):
            if storage_audit.HTML_MARKERS.search(data):
                rep.problems.append(f"{where}: HTML document marker in study data")
            if storage_audit.BODY_KEYS.search(data):
                rep.problems.append(f"{where}: page-body key in study data")
            for p in paths:  # the storage audit's CSV header rule (B4.4 pass 2)
                head = storage_audit.header_problem(Path(p), data)
                if head:
                    rep.problems.append(f"{p}: page-body column {head.decode(errors='replace')!r}")
                    break
            if any(
                p.endswith((".json", ".jsonl", ".ndjson", ".json.gz", ".jsonl.gz", ".ndjson.gz"))
                for p in paths
            ):
                for hit in storage_audit.long_text_keys(data)[:1]:
                    rep.problems.append(f"{where}: long page-body value {hit} in study data")
        else:
            for p in paths:
                why = page_problem(p, data)
                if why:
                    rep.problems.append(f"{p} ({sha[:10]}): {why}")
    commits = _messages(rep)
    rep.stats = {
        "commits": commits,
        "blobs": len(contents),
        "shallow": int(_git("rev-parse", "--is-shallow-repository").strip() == b"true"),
        "private_links": len(rep.private),
        "known_private_links": rep.known_private,
    }
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = report()
    stats = rep.stats
    if a.json:
        print(
            json.dumps(
                {"ok": not rep.problems, "problems": rep.problems, "private": rep.private, **stats},
                indent=1,
            )
        )
    else:
        print(
            f"history audit: {stats['commits']} commits, {stats['blobs']} file versions"
            + (" (shallow clone: partial history)" if stats["shallow"] else "")
        )
        for p in rep.problems:
            print(f"  {p}")
        print(
            f"private links (low, not failing): {len(rep.private)} new, "
            f"{stats['known_private_links']} known (KNOWN_PRIVATE_LINKS)"
        )
        for p in rep.private:
            print(f"  {p}")
        print("OK" if not rep.problems else f"{len(rep.problems)} finding(s)")
    return 1 if rep.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
