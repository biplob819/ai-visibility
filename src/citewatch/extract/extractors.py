"""Citations and consulted sources from verbatim answer envelopes (CIT-01..03, CIT-06).

Citations come only from the API's citation fields: Claude's `web_search_result_location`
citations on text blocks, OpenAI's `url_citation` annotations. A link typed in the answer
text is never a citation (B2). Consulted sources are what the search returned or opened.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .urls import UrlError, canonical_url, publisher_of


@dataclass
class RawCitation:
    url_raw: str
    title: str | None
    quoted_span: str | None
    answer_span: str


@dataclass
class Extracted:
    answer_text: str  # the text the word count is taken from
    citations: list[RawCitation] = field(default_factory=list)
    consulted: dict[str, str | None] = field(default_factory=dict)  # url_raw -> page_age
    skipped: list[str] = field(default_factory=list)  # citation URLs that are not web pages


def extract_claude(responses: Sequence[Mapping[str, Any]]) -> Extracted:
    texts: list[str] = []
    out = Extracted(answer_text="")
    for r in responses:
        for block in r.get("content") or []:
            kind = block.get("type")
            if kind == "text":
                text = block.get("text") or ""
                texts.append(text)
                for c in block.get("citations") or []:
                    if c.get("type") == "web_search_result_location" and c.get("url"):
                        out.citations.append(
                            RawCitation(
                                url_raw=c["url"],
                                title=c.get("title"),
                                quoted_span=c.get("cited_text"),
                                answer_span=text.strip() or (c.get("cited_text") or "").strip(),
                            )
                        )
            elif kind == "web_search_tool_result" and isinstance(block.get("content"), list):
                for res in block["content"]:
                    if res.get("type") == "web_search_result" and res.get("url"):
                        out.consulted.setdefault(res["url"], res.get("page_age"))
    out.answer_text = "".join(texts).strip()
    return out


def extract_openai(responses: Sequence[Mapping[str, Any]]) -> Extracted:
    """The answer span is the text a citation marker follows, back to the previous marker or
    the paragraph start; the citation markers are removed from the counted text (D-43)."""
    out = Extracted(answer_text="")
    kept: list[str] = []
    parts_seen = 0
    for r in responses:
        for item in r.get("output") or []:
            kind = item.get("type")
            if kind == "web_search_call":
                action = item.get("action") or {}
                for src in action.get("sources") or []:
                    if src.get("url"):
                        out.consulted.setdefault(src["url"], None)
                if action.get("type") == "open_page" and action.get("url"):
                    out.consulted.setdefault(action["url"], None)
            elif kind == "message":
                for part in item.get("content") or []:
                    if part.get("type") != "output_text":
                        continue
                    if parts_seen:
                        kept.append("\n\n")  # separate parts, never run words together (v1 L6)
                    parts_seen += 1
                    text = part.get("text") or ""
                    last_span: str | None = None
                    spans = sorted(
                        (
                            a
                            for a in part.get("annotations") or []
                            if a.get("type") == "url_citation"
                        ),
                        key=lambda a: a.get("start_index", 0),
                    )
                    cursor = 0
                    for a in spans:
                        try:
                            s, e = int(a.get("start_index") or 0), int(a.get("end_index") or 0)
                        except (TypeError, ValueError):  # a missing index (v1 L5)
                            s = e = cursor
                        if not (0 <= s <= e <= len(text)) or s < cursor:
                            s = e = cursor  # out of order or out of range: no span of its own
                        before = text[cursor:s]
                        para = before.rsplit("\n\n", 1)[-1].strip()
                        kept.append(before)
                        # a marker right after another one supports the same claim (v1 M1)
                        span = para or last_span
                        if a.get("url"):
                            out.citations.append(
                                RawCitation(
                                    url_raw=a["url"],
                                    title=a.get("title"),
                                    quoted_span=None,
                                    answer_span=span or text[s:e].strip() or a["url"],
                                )
                            )
                        if span:
                            last_span = span
                        cursor = max(cursor, e)
                    kept.append(text[cursor:])
    joined = "".join(kept)
    out.answer_text = "\n\n".join(" ".join(p.split()) for p in joined.split("\n\n") if p.strip())
    return out


def canonical_or_none(url: str) -> str | None:
    try:
        return canonical_url(url)
    except UrlError:
        return None


def host_of(url: str) -> str:
    return urlsplit(url).hostname or ""


def publisher(url: str) -> tuple[str, str | None]:
    return publisher_of(url)
