"""The demo tests need the `demo` extra (streamlit, webauthn, cbor2). A core-only install, such
as gate 7's Python 3.11 golden run, collects none of them rather than erroring."""

from __future__ import annotations

import importlib.util

collect_ignore_glob = (
    []
    if all(importlib.util.find_spec(m) for m in ("streamlit", "webauthn", "cbor2"))
    else ["test_*.py"]
)
