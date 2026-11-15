"""citewatch: measure which web pages AI answers with web search cite, and how fresh they are."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("citewatch")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
