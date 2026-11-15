"""Date candidates from the seven sources of Tech Spec §7.3 (DAT-01, DAT-06).

Every date a page states is kept with its source and a short piece of evidence; nothing is
chosen here (rules.py rejects, resolve.py chooses).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from html.parser import HTMLParser
from typing import Any

from dateutil import parser as dparser

from citewatch.schemas import DateCandidate

SCHEMA_PROPS = {
    "dateModified": "modified",
    "datePublished": "published",
    "lastReviewed": "reviewed",
}
META_PROPS = {
    "article:modified_time": "modified",
    "og:updated_time": "modified",
    "dc.date.modified": "modified",
    "dcterms.modified": "modified",
    "last-modified": "modified",
    "article:published_time": "published",
    "dc.date.issued": "published",
    "dcterms.issued": "published",
}
_DATE_WORDS = (
    r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})"
)
TEXT_PATTERNS = [
    (re.compile(r"page\s+last\s+reviewed\s*:?\s*" + _DATE_WORDS, re.I), "reviewed"),
    (re.compile(r"(?:last\s+)?reviewed\s+on\s*:?\s*" + _DATE_WORDS, re.I), "reviewed"),
    # not "Media last reviewed": NHS pages date their images and videos separately
    (re.compile(r"(?<!page\s)(?<!media\s)last\s+reviewed\s*:?\s*" + _DATE_WORDS, re.I), "reviewed"),
    (re.compile(r"next\s+review\s+(?:due|date)\s*:?\s*" + _DATE_WORDS, re.I), "review_due"),
    (re.compile(r"last\s+updated\s*(?:on)?\s*:?\s*" + _DATE_WORDS, re.I), "modified"),
    (re.compile(r"(?<!last\s)updated\s+on\s*:?\s*" + _DATE_WORDS, re.I), "modified"),
    (re.compile(r"\bpublished\s*(?:on)?\s*:?\s*" + _DATE_WORDS, re.I), "published"),
]
_AGO = re.compile(r"^\s*(a|an|\d+)\s+(day|week|month|year)s?\s+ago\s*$", re.I)
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def parse_date(text: str, *, dayfirst: bool = False) -> dt.date | None:
    """A calendar date from an ISO string, a datetime or prose; None when it is not one."""
    s = (text or "").strip()
    if not s or len(s) > 80 or not re.search(r"\d", s):
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            value = dparser.isoparse(s)
        else:
            value = dparser.parse(s, dayfirst=dayfirst, fuzzy=False, default=dt.datetime(1, 1, 1))
    except (ValueError, OverflowError, TypeError):
        return None
    if value.year < 1000:
        return None
    return value.date()  # the date as the page states it, in its own time zone (not UTC)


def page_age_date(page_age: str, answered_at: dt.datetime) -> dt.date | None:
    """Claude's page_age: relative to the request ("198 days ago", D-35) or an absolute date."""
    m = _AGO.match(page_age or "")
    if m:
        n = 1 if m.group(1).lower() in ("a", "an") else int(m.group(1))
        return (answered_at - dt.timedelta(days=n * _UNIT_DAYS[m.group(2).lower()])).date()
    return parse_date(page_age)


def _cand(*, kind: str, value: dt.date, source: str, evidence: str) -> DateCandidate:
    return DateCandidate.model_validate(
        {"kind": kind, "value": value, "source": source, "evidence": evidence}
    )


def _ev(text: str) -> str:
    t = " ".join(str(text).split())
    return (t[:117] + "...") if len(t) > 120 else (t or "?")


def _walk(node: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(node, Mapping):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _values(v: Any) -> Iterable[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from _values(x)
    elif isinstance(v, Mapping):
        for k in ("@value", "value"):
            if isinstance(v.get(k), str):
                yield v[k]


def structured(html: str, url: str) -> list[DateCandidate]:
    import extruct

    try:
        data = extruct.extract(html, base_url=url, syntaxes=["microdata", "rdfa"], uniform=True)
    except Exception:  # malformed markup never stops a page; the other sources still count
        return []
    out: list[DateCandidate] = []
    for syntax, source in (("microdata", "microdata"), ("rdfa", "microdata")):
        for obj in _walk(data.get(syntax) or []):
            for key, raw in obj.items():
                prop = key.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                if syntax == "rdfa" and "schema.org" not in key:
                    continue  # RDFa Open Graph properties are read as meta tags instead
                kind = SCHEMA_PROPS.get(prop)
                if kind is None:
                    continue
                for v in _values(raw):
                    d = parse_date(v)
                    if d is not None:
                        out.append(
                            _cand(kind=kind, value=d, source=source, evidence=_ev(f"{prop}: {v}"))
                        )
    return out


def json_ld(blocks: list[str]) -> list[DateCandidate]:
    """JSON-LD read directly, walking `@graph` and nested objects; a block without
    `@context` still counts (WHO's pages have none, and extruct drops them)."""
    out: list[DateCandidate] = []
    for raw in blocks:
        try:
            data = json.loads(raw.strip().removeprefix("<!--").removesuffix("-->"), strict=False)
        except ValueError:
            continue
        for obj in _walk(data):
            for key, v in obj.items():
                kind = SCHEMA_PROPS.get(key) if isinstance(key, str) else None
                if kind is None:
                    continue
                for s in _values(v):
                    d = parse_date(s)
                    if d is not None:
                        out.append(
                            _cand(
                                kind=kind, value=d, source="schema_org", evidence=_ev(f"{key}: {s}")
                            )
                        )
    return out


class _Page(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metas: list[tuple[str, str]] = []
        self.text: list[str] = []
        self.ld: list[str] = []
        self._ld: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            name = (a.get("property") or a.get("name") or a.get("http-equiv") or "").lower()
            if name in META_PROPS and a.get("content"):
                self.metas.append((name, a["content"]))
        if tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._ld = []
        elif tag in self.SKIP:
            self._skip += 1
        if tag in (
            "p",
            "div",
            "br",
            "li",
            "tr",
            "dd",
            "dt",
            "h1",
            "h2",
            "h3",
            "h4",
            "span",
            "time",
        ):
            self.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._ld is not None:
            self.ld.append("".join(self._ld))
            self._ld = None
        elif tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._ld is not None:
            self._ld.append(data)
        elif not self._skip:
            self.text.append(data)


def from_html(html: str, url: str) -> list[DateCandidate]:
    out = structured(html, url)
    p = _Page()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    out += json_ld(p.ld)
    for name, content in p.metas:
        d = parse_date(content)
        if d is not None:
            out.append(
                _cand(
                    kind=META_PROPS[name],
                    value=d,
                    source="meta_tag",
                    evidence=_ev(f"{name}: {content}"),
                )
            )
    text = " ".join(" ".join(p.text).split())
    seen: set[tuple[str, int]] = set()
    for rx, kind in TEXT_PATTERNS:
        for m in rx.finditer(text):
            if (kind, m.start(1)) in seen:
                continue
            seen.add((kind, m.start(1)))
            d = parse_date(m.group(1), dayfirst=True)
            if d is not None:
                out.append(
                    _cand(kind=kind, value=d, source="visible_text", evidence=_ev(m.group(0)))
                )
    return out


def from_header(last_modified: str | None) -> list[DateCandidate]:
    d = parse_date(last_modified or "")
    if d is None:
        return []
    return [
        _cand(
            kind="modified",
            value=d,
            source="http_header",
            evidence=_ev(f"Last-Modified: {last_modified}"),
        )
    ]


def from_page_age(page_age: str | None, answered_at: dt.datetime | None) -> list[DateCandidate]:
    if not page_age or answered_at is None:
        return []
    d = page_age_date(page_age, answered_at)
    if d is None:
        return []
    return [
        _cand(kind="modified", value=d, source="page_age", evidence=_ev(f"page_age: {page_age}"))
    ]


def from_sitemap(lastmod: str | None) -> list[DateCandidate]:
    d = parse_date(lastmod or "")
    if d is None:
        return []
    return [_cand(kind="modified", value=d, source="sitemap", evidence=_ev(f"lastmod: {lastmod}"))]
