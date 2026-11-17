"""Fetch the support sample's pages once more to rebuild their kept text (OWNER D-61).

The first kept text glued paragraphs together; `main_text` now breaks lines at block elements.
Each sample page gets one more polite request through the same client (robots, 1 request per
second per host, the study-wide 3-requests-per-page budget, all logged). Only the main text is
written, to the body cache outside the repo; each new fetch time goes to
`data/support_text_fetches.jsonl` so the answer-to-fetch gap (SUP-06) uses it.

    uv run python scripts/refetch_support_text.py studies/uk-health
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from citewatch.cli import fetch_logs_for
from citewatch.fetch import FetchLog, PageHistory, PoliteClient
from citewatch.fetch.pages import body_cache_dir, decode, main_text
from citewatch.schemas import load_study_config
from citewatch.store import RawStore
from citewatch.support import read_sample


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study", type=Path)
    a = ap.parse_args()
    base = a.study
    cfg = load_study_config(base / "study.yaml")
    data = base / "data"
    pages = {
        (p := json.loads(x))["url"]: p
        for x in (data / "page_meta.jsonl").read_text(encoding="utf-8").splitlines()
        if x
    }
    urls = sorted(
        {r["url"] for r in read_sample(base) if pages.get(r["url"], {}).get("outcome") == "ok"}
    )
    client = PoliteClient(
        cfg.user_agent,
        FetchLog(data / "fetch_log.jsonl"),
        history=PageHistory.from_logs(fetch_logs_for(base)),
        store=RawStore(base),
    )
    cache = body_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    (cache / ".citewatch-body-cache").touch()  # finalise deletes only marked caches (D-68)
    out = []
    try:
        for url in urls:
            r = client.get(url, "page")
            row = {
                "url": url,
                "outcome": r.outcome,
                "fetched_at": None
                if r.fetched_at is None
                else r.fetched_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            }
            if r.outcome == "ok" and r.body is not None:
                text = main_text(decode(r.body, r.headers.get("content-type", "")))
                name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] + ".txt"
                (cache / name).write_text(text, encoding="utf-8")
            r.body = None
            out.append(row)
    finally:
        client.close()
    (data / "support_text_fetches.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in out), encoding="utf-8", newline="\n"
    )
    ok = sum(r["outcome"] == "ok" for r in out)
    print(f"refetched {len(out)} sample pages: {ok} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
