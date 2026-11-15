"""`canonical_url` and `publisher_of` (Tech Spec §5, D-4, CIT-04, CIT-05).

One canonical form per page, so shares count pages and publishers, not tracking variants;
`url_raw` keeps the API's spelling. `publisher_of` is shared with the demo lookup (D5.1).
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import tldextract

# click and campaign identifiers that never change the page (D-36 found utm_source=openai)
CLICK_IDS = frozenset(
    {
        "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "fbclid", "msclkid", "yclid",
        "igshid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "mkt_tok", "srsltid", "twclid",
        "li_fat_id", "ttclid", "oly_anon_id", "oly_enc_id", "vero_id", "_ga", "_gl",
    }
)  # fmt: skip
INSTITUTIONAL = ("nhs.uk", "gov.uk", "police.uk", "ac.uk", "sch.uk")
DEFAULT_PORTS = {"http": 80, "https": 443}
_SAFE_PATH = "/:@!$&'()*+,;=-._~"  # no '%': a decoded % is re-encoded, so it is idempotent
_SAFE_QUERY = "/:@!$'()*,;=-._~?"  # no '+': it reads back as a space


class UrlError(ValueError):
    """A URL that cannot be a cited web page."""


def _drop(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in CLICK_IDS


def canonical_url(url: str) -> str:
    """Lower-case scheme and host (IDN as punycode), no fragment, user info or default port,
    `utm_*` and known click IDs removed, other query parameters kept in order, percent-
    encoding normalised. Idempotent: canonical_url(canonical_url(u)) == canonical_url(u)."""
    s = url.strip()
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in s):
        raise UrlError(f"{url!r} contains whitespace or control characters")
    try:
        p = urlsplit(s)
        port = p.port
    except ValueError as exc:
        raise UrlError(f"{url!r} is not a URL ({exc})") from exc
    scheme = p.scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlError(f"{url!r} is not an http(s) URL")
    host = (p.hostname or "").rstrip(".")
    if not host:
        raise UrlError(f"{url!r} has no host")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        host = host.lower()
    shown = f"[{host}]" if ":" in host else host
    netloc = shown if port in (None, DEFAULT_PORTS[scheme]) else f"{shown}:{port}"
    path = quote(unquote(p.path), safe=_SAFE_PATH) or "/"
    kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _drop(k)]
    query = urlencode(kept, quote_via=quote, safe=_SAFE_QUERY) if kept else ""
    return urlunsplit((scheme, netloc, path, query, ""))


@lru_cache(maxsize=1)
def _extractor() -> tldextract.TLDExtract:
    # the bundled Public Suffix List snapshot: no network, the same answer on every machine
    return tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def _host(url_or_domain: str) -> str:
    s = url_or_domain.strip()
    if "://" not in s:
        s = "http://" + s
    try:
        host = urlsplit(s).hostname or ""
    except ValueError as exc:
        raise UrlError(f"{url_or_domain!r} is not a URL or domain ({exc})") from exc
    host = host.rstrip(".")
    try:
        return host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return host.lower()


def publisher_of(url_or_domain: str) -> tuple[str, str | None]:
    """(publisher, publisher_group) per D-4: the registrable domain, except under the UK
    institutional suffixes, where `www.` (or the bare suffix) maps to the suffix itself and
    other hosts keep their registrable domain with the suffix as their group."""
    host = _host(url_or_domain)
    if not host:
        raise UrlError(f"{url_or_domain!r} has no host")
    for inst in INSTITUTIONAL:
        if host == inst or host == "www." + inst:
            return inst, None
        if host.endswith("." + inst):
            labels = host[: -len(inst) - 1].split(".")
            # the PSL lists *.sch.uk: a school is school.county.sch.uk (v1 L1)
            take = 2 if inst == "sch.uk" and len(labels) >= 2 else 1
            return ".".join([*labels[-take:], inst]), inst
    ex = _extractor()(host)
    if ex.suffix and ex.domain:
        return f"{ex.domain}.{ex.suffix}", None
    return host, None  # an IP address, localhost or an unknown suffix: the host itself
