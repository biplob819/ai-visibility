#!/usr/bin/env python3
"""Build the DAT-04 date test set: fetch pages politely, keep only their date-bearing parts.

Fetches each URL once through citewatch's own PoliteClient (robots, 1 req/s per host, the
flagship user agent), then writes a trimmed snapshot to tests/fixtures/dates/pages/: the
<head> date metas and JSON-LD, microdata date properties, and the text lines that carry a
date phrase. No full page is kept. The fetch log and store go to a scratch folder.

Usage: python scripts/build_date_fixtures.py <scratch-dir> URL [URL ...]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from citewatch.dates.candidates import META_PROPS, TEXT_PATTERNS  # noqa: E402
from citewatch.fetch import FetchLog, PoliteClient  # noqa: E402
from citewatch.fetch.pages import decode  # noqa: E402
from citewatch.schemas import load_study_config  # noqa: E402
from citewatch.store import RawStore  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "dates" / "pages"
_DATE_PROP = re.compile(r'itemprop\s*=\s*["\'](dateModified|datePublished|lastReviewed)["\']', re.I)


class _Keep(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # entities inside JSON-LD stay valid JSON
        self.head: list[str] = []
        self.ld: list[str] = []
        self.micro: list[str] = []
        self.text: list[str] = []
        self._in_ld = False
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        raw = self.get_starttag_text() or ""
        if tag == "meta":
            name = (a.get("property") or a.get("name") or a.get("http-equiv") or "").lower()
            if name in META_PROPS:
                self.head.append(raw)
            elif _DATE_PROP.search(raw):
                self.micro.append(raw)
        elif tag == "time" and _DATE_PROP.search(raw):
            self.micro.append(raw + "</time>")
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld, self._buf = True, []
        elif tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag in ("p", "div", "br", "li", "tr", "dd", "dt", "h1", "h2", "h3", "span", "time"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.ld.append("".join(self._buf))
            self._in_ld = False
        elif tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif not self._skip:
            self.text.append(data)


_LD_KEEP = ("dateModified", "datePublished", "lastReviewed")
_PHRASE = re.compile(
    r"(review|updated|published|modified|posted|date)[^\n]{0,40}"
    r"(\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)


def prune_ld(blocks: list[str]) -> list[str]:
    """Only the date fields of each JSON-LD object (no page text), one flat object each."""
    out = []
    for raw in blocks:
        try:
            data = json.loads(raw.strip(), strict=False)
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                dates = {k: node[k] for k in _LD_KEEP if isinstance(node.get(k), str)}
                if dates:
                    obj = {"@context": "https://schema.org", "@type": node.get("@type", "Thing")}
                    out.append(json.dumps({**obj, **dates}, sort_keys=True))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return list(dict.fromkeys(out))


def trim(html: str) -> str:
    k = _Keep()
    k.feed(html)
    k.close()
    lines = [" ".join(x.split()) for x in "".join(k.text).split("\n")]
    dated = [
        x[:300]
        for x in lines
        if x and (any(rx.search(x) for rx, _ in TEXT_PATTERNS) or _PHRASE.search(x))
    ]
    parts = ["<html><head>", *k.head]
    parts += [f'<script type="application/ld+json">{x}</script>' for x in prune_ld(k.ld)]
    parts += ["</head><body>"]
    if k.micro:
        parts += ['<div itemscope itemtype="https://schema.org/WebPage">', *k.micro, "</div>"]
    parts += [f"<p>{x}</p>" for x in dict.fromkeys(dated)]
    parts += ["</body></html>"]
    return "\n".join(parts) + "\n"


def main(argv: list[str]) -> int:
    scratch, urls = Path(argv[0]), argv[1:]
    cfg = load_study_config(ROOT / "studies" / "uk-health" / "study.yaml")
    store = RawStore(scratch)
    client = PoliteClient(
        cfg.user_agent, FetchLog(scratch / "data" / "fetch_log.jsonl"), store=store
    )
    OUT.mkdir(parents=True, exist_ok=True)
    index = {}
    try:
        for url in urls:
            r = client.get(url)
            slug = re.sub(r"[^a-z0-9]+", "-", url.split("://", 1)[1].lower()).strip("-")[:60]
            slug += "-" + hashlib.sha256(url.encode()).hexdigest()[:6]
            print(f"{r.outcome:18} {r.status} {url}")
            if r.outcome != "ok" or r.body is None:
                continue
            html = decode(r.body, r.headers.get("content-type", ""))
            (OUT / f"{slug}.html").write_text(trim(html), encoding="utf-8")
            index[slug] = {
                "url": url,
                "final_url": r.final_url,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                "last_modified": r.headers.get("last-modified"),
            }
    finally:
        client.close()
    (OUT.parent / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{len(index)} snapshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
