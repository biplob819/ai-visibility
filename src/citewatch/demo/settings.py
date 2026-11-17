"""Deployment settings for the demo (DEM-03, DEM-04): every secret comes from the host's secret
store (st.secrets on Streamlit Community Cloud) or the environment, never from the repo.
Functions here name missing secrets but never return or print a value.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx

from citewatch.demo.kv import KV, SqliteKV, UpstashKV
from citewatch.demo.live import ProviderKeys

OWNER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
PASSKEY_SECRETS = (
    "CITEWATCH_DEMO_CODE_HASH",
    "CITEWATCH_DEMO_CODE_SALT",
    "CITEWATCH_DEMO_RP_ID",
    "CITEWATCH_DEMO_ORIGIN",
)
KV_SECRETS = ("CITEWATCH_DEMO_KV_URL", "CITEWATCH_DEMO_KV_TOKEN")
LOCAL_STORE = "CITEWATCH_DEMO_LOCAL_STORE"  # a SQLite path; local development only
ALL_SECRETS = (*OWNER_KEYS, *PASSKEY_SECRETS, *KV_SECRETS)


def _set(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name, "") or "").strip())


def missing(env: Mapping[str, str]) -> list[str]:
    """Names of the secrets live mode still needs (the owner's keys are optional: without
    them, signed-in visitors can still use their own)."""
    out = [n for n in PASSKEY_SECRETS if not _set(env, n)]
    if not _set(env, LOCAL_STORE):
        out += [n for n in KV_SECRETS if not _set(env, n)]
    return out


def live_problem(env: Mapping[str, str]) -> str | None:
    """Why live mode is off on this deployment, or None."""
    if missing(env):
        return "Live mode is not configured on this deployment; lookup mode works."
    return None


def make_kv(env: Mapping[str, str], client: httpx.Client | None = None) -> KV:
    """The hosted KV when its URL and token are set, else the local SQLite file named by
    CITEWATCH_DEMO_LOCAL_STORE (development only)."""
    if all(_set(env, n) for n in KV_SECRETS):
        return UpstashKV(env["CITEWATCH_DEMO_KV_URL"], env["CITEWATCH_DEMO_KV_TOKEN"], client)
    if _set(env, LOCAL_STORE):
        return SqliteKV(Path(env[LOCAL_STORE]))
    raise ValueError("no demo store configured")


def owner_keys(env: Mapping[str, str]) -> ProviderKeys:
    return ProviderKeys(
        anthropic=str(env.get("ANTHROPIC_API_KEY", "") or ""),
        openai=str(env.get("OPENAI_API_KEY", "") or ""),
    )


def has_owner_keys(env: Mapping[str, str]) -> bool:
    return any(_set(env, n) for n in OWNER_KEYS)
