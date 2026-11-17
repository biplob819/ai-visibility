"""citewatch: measure which web pages AI answers with web search cite, and how fresh they are.

Public API (semver, see docs/versioning.md): the results format in `citewatch.schemas`, and
`canonical_url`, `publisher_of`, `UrlError`, `lookup`, `read_cards` and `NotCited`, importable
from here or from `citewatch.extract.urls` and `citewatch.cards`. They load on first use, so
`import citewatch` (and the CLI) stays fast.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

try:
    __version__ = version("citewatch")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"

if TYPE_CHECKING:
    from citewatch import schemas
    from citewatch.cards import NotCited, lookup, read_cards
    from citewatch.extract.urls import UrlError, canonical_url, publisher_of

_LAZY = {
    "canonical_url": "citewatch.extract.urls",
    "publisher_of": "citewatch.extract.urls",
    "UrlError": "citewatch.extract.urls",
    "lookup": "citewatch.cards",
    "read_cards": "citewatch.cards",
    "NotCited": "citewatch.cards",
}

__all__ = [
    "NotCited",
    "UrlError",
    "__version__",
    "canonical_url",
    "lookup",
    "publisher_of",
    "read_cards",
    "schemas",
]


def __getattr__(name: str) -> Any:
    if name == "schemas":
        return import_module("citewatch.schemas")
    if name in _LAZY:
        value = getattr(import_module(_LAZY[name]), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'citewatch' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
