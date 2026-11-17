"""The end-to-end study test replays recorded OpenAI responses through the real SDK, so it
needs the `openai` extra. A core-only install, such as gate 7's Python 3.11 golden run,
skips collecting it rather than erroring."""

from __future__ import annotations

import importlib.util

collect_ignore = (
    []
    if all(importlib.util.find_spec(m) for m in ("openai", "httpx2"))
    else ["test_own_study_end_to_end.py"]
)
