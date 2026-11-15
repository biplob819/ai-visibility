"""The polite fetcher (Tech Spec §7.2, A2.2)."""

from .client import FetchResult, PoliteClient
from .history import PageHistory
from .keys import norm_host, norm_url, page_key
from .log import FetchLog
from .pages import FETCH_CODE_VERSION, Page, PagesResult, fetch_key, fetch_pages, main_text
from .rate import HostLimiter
from .robots import ROBOTS_TOKEN, RobotsCache

__all__ = [
    "FETCH_CODE_VERSION",
    "ROBOTS_TOKEN",
    "FetchLog",
    "FetchResult",
    "HostLimiter",
    "Page",
    "PageHistory",
    "PagesResult",
    "PoliteClient",
    "RobotsCache",
    "fetch_key",
    "fetch_pages",
    "main_text",
    "norm_host",
    "norm_url",
    "page_key",
]
