"""Untrusted text in the page's HTML (quotes from cited pages, URLs, publisher names, card text).

The page renders its HTML with `st.markdown(..., unsafe_allow_html=True)`, so escaping `<`, `>`
and `&` is not enough: markdown still runs. A blank line inside a quote would end the HTML block
and let the rest render as markdown (an image that loads from a stranger's server, a link), and
Streamlit's own syntax (`:red[...]`, `$...$` maths, `:emoji:`) would run too. So every piece of
untrusted text goes through `text`, which collapses all whitespace (no line breaks can reach the
output, so the whole block stays one HTML block) and writes each character markdown or Streamlit
could treat as syntax as a numeric character reference: it shows as itself and parses as
nothing. Links go through `link`, which allows only http(s) URLs.
"""

from __future__ import annotations

from html import escape

# Markdown and Streamlit syntax characters, plus the HTML ones; '.', ',', '-', '/' and letters
# stay as they are so ordinary names read normally in the source too.
_SYNTAX = frozenset("\\`*_{}[]()<>#+!|~:$&\"'=^%@")


def text(value: object) -> str:
    """`value` as inert text for HTML that markdown will also parse."""
    flat = " ".join(str(value).split())
    return "".join(f"&#{ord(c)};" if c in _SYNTAX else c for c in flat)


def attr(value: object) -> str:
    """`value` for a quoted HTML attribute: whitespace removed, then HTML-escaped."""
    return escape("".join(str(value).split()), quote=True)


def link(url: str) -> str:
    """An outbound link for an http(s) URL; any other value is shown as plain text."""
    clean = "".join(url.split())
    if clean.lower().startswith(("https://", "http://")):
        return f"<a href='{attr(clean)}' rel='noopener nofollow' target='_blank'>{text(clean)}</a>"
    return text(url)
