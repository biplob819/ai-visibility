"""Page identity, the same as the gate-8 audit's (`scripts/fetch_audit.py`), so the fetcher
never makes a request the audit would count against it (FET-08)."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def norm_host(host: str) -> str:
    """Lower case, no trailing dot, no port, IPv6 without brackets."""
    h = host.strip().lower()
    if h.startswith("["):
        h = h[1 : h.index("]")] if "]" in h else h[1:]
    elif h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h.rstrip(".")


def norm_url(url: str) -> str:
    """Lower-case scheme and host, no default port, no fragment, percent-encoding decoded.
    Raises ValueError on a malformed URL."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = norm_host(parts.hostname or "")
    port = parts.port
    shown = f"[{host}]" if ":" in host else host
    netloc = shown if port in (None, DEFAULT_PORTS.get(scheme)) else f"{shown}:{port}"
    return urlunsplit((scheme, netloc, unquote(parts.path) or "/", unquote(parts.query), ""))


def page_key(url: str) -> str:
    """http/https, a trailing slash and query order are the same page."""
    rest = norm_url(url).split("://", 1)[-1]
    path, _, query = rest.partition("?")
    if path.count("/") > 1:
        path = path.rstrip("/")
    return path + ("?" + "&".join(sorted(query.split("&"))) if query else "")


_MARKUP = str.maketrans({"&": "%26", "<": "%3C", ">": "%3E", '"': "%22", "'": "%27"})


def clean(text: str) -> str:
    """Server-controlled text made safe to store or log: markup characters percent-encoded,
    so no stored record ever carries page markup (NFR6, A2.2 v4 M1). URLs keep their page
    identity, since page keys decode percent-encoding."""
    return text.translate(_MARKUP)


def ascii_host(host: str) -> str:
    """The punycode form, so `bücher.example` and `xn--bcher-kva.example` are one host for
    the rate limit and robots (v2 M-4)."""
    h = norm_host(host)
    try:
        return h.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return h


def host_of(url: str) -> str:
    return norm_host(urlsplit(url).hostname or "")
