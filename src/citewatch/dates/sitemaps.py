"""Sitemap `lastmod` from sitemaps listed in robots.txt (Tech Spec §7.3, DAT-05, E4).

Fetched through the polite client (robots, rate, budget, log), capped at 10 MB decoded,
parsed without DTDs or entity expansion, at most one level of sitemap index. Each host's
`loc -> lastmod` map is cached in the store, so a sitemap is read once for the study.
"""

from __future__ import annotations

import io
import zlib
from typing import Any
from urllib.parse import urlsplit

from defusedxml import ElementTree as SafeET

from citewatch.extract.urls import UrlError, canonical_url
from citewatch.fetch.robots import ROBOTS_CODE_VERSION, origin_of
from citewatch.store import RawStore, stage_key

SITEMAP_CODE_VERSION = "sitemap-1"
MAX_SITEMAP_BYTES = 10 * 1024 * 1024
MAX_CHILD_SITEMAPS = 50
MAX_ENTRIES = 200_000
_UNCLEAN = {"%26": "&", "%3C": "<", "%3E": ">", "%22": '"', "%27": "'", "%5C": "\\"}


def _unclean(s: str) -> str:
    for k, v in _UNCLEAN.items():
        s = s.replace(k, v)
    return s


def sitemap_urls(store: RawStore, origin: str) -> list[str]:
    """`Sitemap:` lines from the stored robots answer for this origin (robots must be read
    first, so only sitemaps a site lists are ever requested)."""
    key = stage_key("robots", ROBOTS_CODE_VERSION, {"origin": origin}, "")
    if not store.has("robots", key):
        return []
    rec = store.get("robots", key)
    out = []
    for line in rec.get("directives") or []:
        name, _, value = line.partition(":")
        if name.strip().lower() == "sitemap" and value.strip():
            out.append(_unclean(value.strip()))
    return out[:MAX_CHILD_SITEMAPS]


def _decode(body: bytes) -> bytes | None:
    if body[:2] != b"\x1f\x8b":
        return body
    out = bytearray()
    rest = body
    while rest[:2] == b"\x1f\x8b":  # every member of a multi-member gzip file
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out += d.decompress(rest, MAX_SITEMAP_BYTES + 1 - len(out))
        except zlib.error:
            return None
        if len(out) > MAX_SITEMAP_BYTES or d.unconsumed_tail:
            return None  # over the 10 MB decoded cap
        rest = d.unused_data
    return bytes(out)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(body: bytes) -> tuple[dict[str, str], list[str]]:
    """(loc -> lastmod for <url> entries, child sitemap locs for a <sitemapindex>)."""
    data = _decode(body)
    if data is None:
        return {}, []
    try:
        root = SafeET.parse(io.BytesIO(data), forbid_dtd=True, forbid_entities=True).getroot()
    except Exception:  # malformed or hostile XML is no sitemap
        return {}, []
    if root is None:
        return {}, []
    entries: dict[str, str] = {}
    children: list[str] = []
    kind = _local(root.tag)
    for node in root:
        fields = {_local(ch.tag): (ch.text or "").strip() for ch in node}
        loc = fields.get("loc")
        if not loc:
            continue
        if kind == "sitemapindex":
            children.append(loc)
        elif fields.get("lastmod") and len(entries) < MAX_ENTRIES:
            entries[loc] = fields["lastmod"]
    return entries, children


def host_lastmods(client: Any, store: RawStore, origin: str) -> dict[str, str]:
    """Canonical URL -> lastmod for every <url> on this origin's listed sitemaps (cached)."""
    key = stage_key("sitemap", SITEMAP_CODE_VERSION, {"origin": origin}, "")
    if store.has("sitemap", key):
        return dict(store.get("sitemap", key).get("lastmod") or {})
    host = urlsplit(origin).hostname
    found: dict[str, str] = {}
    queue = [(u, 0) for u in sitemap_urls(store, origin)]
    seen: set[str] = set()
    transient = False
    while queue and len(seen) < MAX_CHILD_SITEMAPS:
        url, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        r = client.get(url, "sitemap")
        if r.outcome != "ok" or not r.body:
            if not (r.status in (404, 410) or r.outcome in ("robots_disallowed", "blocked")):
                transient = True  # a 5xx or a timeout: try again on a later run
            continue
        entries, children = parse_sitemap(r.body)
        for loc, lastmod in entries.items():
            try:
                c = canonical_url(loc)
            except UrlError:
                continue
            if urlsplit(c).hostname == host:
                found.setdefault(c, lastmod)
        if depth == 0:
            queue.extend((c, 1) for c in children)  # one index level at most
    if not transient:  # a temporary failure is never cached as "no sitemap" (A2.3 v1 low)
        store.put("sitemap", key, {"origin": origin, "sitemaps": sorted(seen), "lastmod": found})
    return found


def origins_of(urls: list[str]) -> list[str]:
    return sorted({origin_of(u) for u in urls})


__all__ = ["MAX_SITEMAP_BYTES", "host_lastmods", "origins_of", "parse_sitemap", "sitemap_urls"]
