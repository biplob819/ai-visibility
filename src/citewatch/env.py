"""Provider keys and `.env` loading (STO-04). Key values are never printed or logged."""

from __future__ import annotations

import os
from pathlib import Path

PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


class MissingKeyError(RuntimeError):
    """A provider's key is not set. The message names the exact variable."""


def load_dotenv(path: Path) -> list[str]:
    """Read KEY=VALUE lines into the environment without overriding variables that are already
    set. Returns the names it set (never the values)."""
    if not path.is_file():
        return []
    loaded = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if name and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def key_for(provider: str) -> str:
    var = PROVIDER_KEYS[provider]
    value = os.environ.get(var, "")
    if not value.strip():
        raise MissingKeyError(
            f"{var} is not set (needed for {provider}); add it to .env or the environment"
        )
    return value


def key_status(providers: list[str]) -> dict[str, bool]:
    """Which provider variables are set, by name. Never returns a value."""
    return {PROVIDER_KEYS[p]: bool(os.environ.get(PROVIDER_KEYS[p], "").strip()) for p in providers}
