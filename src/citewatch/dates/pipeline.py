"""page_meta.jsonl from the store: fetch records, sitemaps and Claude page ages."""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from citewatch.fetch import Page, fetch_key
from citewatch.schemas import DateCandidate, PageMeta
from citewatch.store import RawStore

from .candidates import from_header, from_html, from_page_age, from_sitemap
from .resolve import resolve_dates

OUTCOMES = frozenset(
    {
        "ok",
        "robots_disallowed",
        "blocked",
        "gated",
        "not_html",
        "fetch_error",
        "too_large",
        "not_fetched",
    }
)


def analyse(page: Page) -> dict[str, Any]:
    """Run inside the fetch stage, while the body is still in memory (A2.2 `analyse`)."""
    cands = from_html(page.html, page.final_url) + from_header(page.headers.get("last-modified"))
    return {"candidates": [c.model_dump(mode="json") for c in cands]}


def _ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def page_ages(base: Path) -> dict[str, list[tuple[str, dt.datetime]]]:
    """Canonical URL -> [(page_age, answered_at)] from consulted.jsonl and answers.jsonl."""
    data = base / "data"
    answered: dict[tuple[int, str, str], dt.datetime] = {}
    if (data / "answers.jsonl").is_file():
        for line in (data / "answers.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                a = json.loads(line)
                t = _ts(a.get("answered_at"))
                if t is not None:
                    answered[(a["run"], a["question_id"], a["model"])] = t
    out: dict[str, list[tuple[str, dt.datetime]]] = defaultdict(list)
    if (data / "consulted.jsonl").is_file():
        for line in (data / "consulted.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                c = json.loads(line)
                t = answered.get((c["run"], c["question_id"], c["model"]))
                if c.get("page_age") and t is not None:
                    out[c["url"]].append((c["page_age"], t))
    return out


def build_page_meta(
    base: Path, urls: list[str], lastmods: dict[str, str] | None = None
) -> list[PageMeta]:
    store = RawStore(base)
    ages = page_ages(base)
    lastmods = lastmods or {}
    metas: list[PageMeta] = []
    for url in sorted(set(urls)):
        key = fetch_key(url)
        rec = store.get("fetch", key) if store.has("fetch", key) else None
        cands = [DateCandidate.model_validate(c) for c in (rec or {}).get("candidates") or []]
        cands += from_sitemap(lastmods.get(url))
        for age, at in ages.get(url, []):
            cands += from_page_age(age, at)
        outcome = (rec or {}).get("outcome") or "not_fetched"
        if outcome not in OUTCOMES:
            outcome = "fetch_error"
        fetched_at = _ts((rec or {}).get("fetched_at"))
        status = (rec or {}).get("status")
        metas.append(
            resolve_dates(
                url,
                outcome=outcome if fetched_at or outcome != "ok" else "fetch_error",
                status=status,
                fetched_at=fetched_at,
                final_url=(rec or {}).get("final_url"),
                candidates=cands,
            )
        )
    return metas


def write_page_meta(base: Path, metas: list[PageMeta]) -> Path:
    path = base / "data" / "page_meta.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(m.model_dump(mode="json"), sort_keys=True) + "\n" for m in metas),
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(path)
    return path
