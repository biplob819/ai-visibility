"""AI Visibility: which pages AI answers cite for UK health questions, and how fresh they are."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ai-visibility")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
