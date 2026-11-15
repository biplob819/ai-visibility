"""Date resolution (Tech Spec §7.3, A2.3)."""

from .candidates import (
    from_header,
    from_html,
    from_page_age,
    from_sitemap,
    page_age_date,
    parse_date,
)
from .pipeline import analyse, build_page_meta, page_ages, write_page_meta
from .resolve import PRECEDENCE, choose, resolve_dates
from .rules import apply_rules
from .sitemaps import host_lastmods, parse_sitemap, sitemap_urls

__all__ = [
    "PRECEDENCE",
    "analyse",
    "apply_rules",
    "build_page_meta",
    "choose",
    "from_header",
    "from_html",
    "from_page_age",
    "from_sitemap",
    "host_lastmods",
    "page_age_date",
    "page_ages",
    "parse_date",
    "parse_sitemap",
    "resolve_dates",
    "sitemap_urls",
    "write_page_meta",
]
