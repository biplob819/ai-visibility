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
    r"((?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})"
)
TEXT_PATTERNS = [
    (re.compile(r"page\s+last\s+reviewed\s*:?\s*" + _DATE_WORDS, re.I), "reviewed"),
    # a bare "Last reviewed" or "Reviewed on" counts only at the start of its own line: a
    # related-page card ("Other page - Last reviewed: ...") or a comment byline is not the
    # page's review, and "Media last reviewed" (NHS images and videos) never starts with it
    # (A2.3 v3 M1, L3)
    (
        re.compile(r"^[ \t]*(?:last\s+)?reviewed\s+on\s*:?\s*" + _DATE_WORDS, re.I | re.M),
        "reviewed",
    ),
    (re.compile(r"^[ \t]*last\s+reviewed\s*:?\s*" + _DATE_WORDS, re.I | re.M), "reviewed"),
    (re.compile(r"next\s+review\s+(?:due|date)\s*:?\s*" + _DATE_WORDS, re.I), "review_due"),
    (re.compile(r"last\s+updated\s*(?:on)?\s*:?\s*" + _DATE_WORDS, re.I), "modified"),
    (re.compile(r"(?<!last\s)updated\s+on\s*:?\s*" + _DATE_WORDS, re.I), "modified"),
    (re.compile(r"\bpublished\s*(?:on)?\s*:?\s*" + _DATE_WORDS, re.I), "published"),
]
_AGO = re.compile(r"^\s*(a|an|\d+)\s+(day|week|month|year)s?\s+ago\s*$", re.I)
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


_NUMERIC = re.compile(
    r"^\W*(?:[A-Za-z]{3,9}\.?,?\s+)?(\d{1,2})([/.\- ])(\d{1,2})\2(\d{2}|\d{4})(?!\d)"
)


def parse_date(text: str, *, dayfirst: bool = False) -> dt.date | None:
    """A calendar date as the page states it; None when it is not a full, unambiguous date.

    ISO strings keep their own time zone (never shifted to UTC). A numeric date whose day and
    month could be swapped (05/10/2024) is ambiguous and dropped; so is a date with no day or
    no year ("June 2024", "2019"): nothing is invented (A2.3 v1 M3). `dayfirst` is kept for
    callers; month names make prose unambiguous."""
    s = (text or "").strip()
    if not s or len(s) > 80 or not re.search(r"\d", s):
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            try:
                return dparser.isoparse(s).date()
            except ValueError:  # "2021-05-01 09:00:00 +0000" (Ruby, Rails): the date as written
                return dt.date.fromisoformat(s[:10])
        m = _NUMERIC.match(s)
        if m:  # whatever follows it (a time, " - 10:00"), the day-month order decides
            a, b, y = int(m.group(1)), int(m.group(3)), m.group(4)
            if len(y) == 2 or (a <= 12 and b <= 12 and a != b):
                return None  # a two-digit year or a swappable day and month (v2 M2)
            y = int(y)
            day, month = (a, b) if a > 12 or a == b else (b, a)
            return dt.date(y, month, day)
        one = dparser.parse(s, fuzzy=False, default=dt.datetime(1, 1, 1))
        two = dparser.parse(s, fuzzy=False, default=dt.datetime(2, 2, 2))
    except (ValueError, OverflowError, TypeError):
        return None
    if one.date() != two.date() or one.year < 1000:
        return None  # a part of the date was missing and would have been invented
    return one.date()


def page_age_date(page_age: str, answered_at: dt.datetime) -> dt.date | None:
    """Claude's page_age: relative to the request ("198 days ago", D-35) or an absolute date."""
    m = _AGO.match(page_age or "")
    if m:
        n = 1 if m.group(1).lower() in ("a", "an") else int(m.group(1))
        try:
            return (answered_at - dt.timedelta(days=n * _UNIT_DAYS[m.group(2).lower()])).date()
        except (OverflowError, ValueError):  # "3000 years ago" (v3 L1)
            return None
    return parse_date(page_age)


def _cand(*, kind: str, value: dt.date, source: str, evidence: str) -> DateCandidate:
    return DateCandidate.model_validate(
        {"kind": kind, "value": value, "source": source, "evidence": evidence}
    )


def _ev(text: str) -> str:
    t = " ".join(str(text).split())
    return (t[:117] + "...") if len(t) > 120 else (t or "?")


def _walk(node: Any, limit: int = 100_000) -> Iterator[Mapping[str, Any]]:
    """Every mapping, iteratively (deep nesting never raises RecursionError)."""
    stack = [node]
    while stack and limit > 0:
        limit -= 1
        cur = stack.pop()
        if isinstance(cur, Mapping):
            yield cur
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur, list):
            stack.extend(reversed(cur))


_PAGE_SUFFIXES = ("Page", "Article")
_PAGE_TYPES = frozenset({"BlogPosting", "Report", "HealthTopicContent", "SocialMediaPosting"})


def _is_page(obj: Mapping[str, Any]) -> bool:
    types = obj.get("@type", obj.get("type"))
    if isinstance(types, str):
        names = [types]
    elif isinstance(types, list):
        names = [x for x in types if isinstance(x, str)]
    else:
        names = []  # a number or boolean @type is no page type (v4 M2)
    names = [n.rsplit("/", 1)[-1] for n in names]
    return any(n.endswith(_PAGE_SUFFIXES) or n in _PAGE_TYPES for n in names)


def page_objects(data: Any) -> list[Mapping[str, Any]]:
    """The objects whose dates are the page's own: top-level objects and `@graph` members that
    are a page or article (or untyped), and their `mainEntity`. Never an image, comment,
    citation, author, publisher or the WebSite (A2.3 v1 M2)."""
    tops: list[Any] = data if isinstance(data, list) else [data]
    found: list[Mapping[str, Any]] = []
    queue = list(tops)
    while queue:
        obj = queue.pop(0)
        if isinstance(obj, list):
            queue.extend(obj)
            continue
        if not isinstance(obj, Mapping):
            continue
        if "@graph" in obj:
            queue.extend(obj["@graph"] if isinstance(obj["@graph"], list) else [obj["@graph"]])
        untyped = "@type" not in obj and "type" not in obj
        if _is_page(obj) or (untyped and "@graph" not in obj):
            found.append(obj)
            for k in ("mainEntity", "mainEntityOfPage"):
                sub = obj.get(k)
                for s in sub if isinstance(sub, list) else [sub]:
                    if isinstance(s, Mapping) and _is_page(s):
                        found.append(s)
    return found


def _values(v: Any, limit: int = 10_000) -> Iterable[str]:
    """Strings of a value, iteratively (deeply nested lists never raise, v3 L2)."""
    stack = [v]
    while stack and limit > 0:
        limit -= 1
        cur = stack.pop()
        if isinstance(cur, str):
            yield cur
        elif isinstance(cur, list):
            stack.extend(reversed(cur))
        elif isinstance(cur, Mapping):
            for k in ("@value", "value"):
                if isinstance(cur.get(k), str):
                    yield cur[k]


def structured(html: str, url: str) -> list[DateCandidate]:
    import extruct

    try:
        data = extruct.extract(html, base_url=url, syntaxes=["microdata", "rdfa"], uniform=True)
    except Exception:  # malformed markup never stops a page; the other sources still count
        return []
    out: list[DateCandidate] = []
    for syntax, source in (("microdata", "microdata"), ("rdfa", "microdata")):
        objs = (
            page_objects(data.get(syntax) or [])
            if syntax == "microdata"
            else list(_walk(data.get(syntax) or []))
        )
        for obj in objs:
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
        text = raw.strip().removeprefix("<!--").removesuffix("-->").strip()
        text = re.sub(r"^(?://\s*)?<!\[CDATA\[|(?://\s*)?\]\]>$", "", text).strip()
        try:
            data = json.loads(text, strict=False)
        except (ValueError, RecursionError):
            try:  # a trailing comma is a common slip; nothing else is repaired
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", text), strict=False)
            except (ValueError, RecursionError):
                continue
        for obj in page_objects(data):
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


# block elements, and the inline ones a page sets a date line in (a byline span, a <time>)
LINE_TAGS = frozenset(
    [
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "td",
        "th",
        "dd",
        "dt",
        "dl",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "aside",
        "header",
        "footer",
        "main",
        "nav",
        "figure",
        "figcaption",
        "blockquote",
        "table",
        "hr",
        "small",
        "span",
        "time",
        "address",
        "details",
        "summary",
    ]
)


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
        if tag == "script" and a.get("type", "").strip().lower().startswith("application/ld+json"):
            self._ld = []
        elif tag in self.SKIP:
            self._skip += 1
        if tag in LINE_TAGS:
            self.text.append("\n")  # an element of its own starts a line (A2.3 v4 M1)

    def handle_endtag(self, tag: str) -> None:
        if tag in LINE_TAGS:
            self.text.append("\n")  # and ends one
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


def _safely(fn: Any, *args: Any) -> list[DateCandidate]:
    try:
        return list(fn(*args))
    except Exception:  # one failing source never drops the others (v4 M2)
        return []


def from_html(html: str, url: str) -> list[DateCandidate]:
    out = _safely(structured, html, url)
    p = _Page()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    out += _safely(json_ld, p.ld)
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
    text = "\n".join(" ".join(line.split()) for line in "".join(p.text).split("\n"))
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
