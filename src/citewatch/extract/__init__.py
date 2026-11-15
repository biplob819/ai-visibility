"""Citation extraction and publisher mapping (Tech Spec §5, A2.1)."""

from .extractors import extract_claude, extract_openai
from .stage import EXTRACT_VERSION, ExtractResult, extract_envelope, run_extract, unique_cited_urls
from .urls import UrlError, canonical_url, publisher_of

__all__ = [
    "EXTRACT_VERSION",
    "ExtractResult",
    "UrlError",
    "canonical_url",
    "extract_claude",
    "extract_envelope",
    "extract_openai",
    "publisher_of",
    "run_extract",
    "unique_cited_urls",
]
