"""Judge the support sample live (SUP-03). Paid: run only with the owner's approval.

    uv run python scripts/judge_support.py studies/uk-health --max-cost 6

Writes `data/support_verdicts.jsonl` (SupportVerdict rows) and `data/support_replacements.jsonl`
(the replacement log). Page text stays in the body cache outside the repo until `--finalise`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from citewatch.env import load_dotenv
from citewatch.fetch.pages import body_cache_dir
from citewatch.schemas import load_questions, load_study_config
from citewatch.support import read_sample
from citewatch.support.judge import (
    SupportJudgingIncomplete,
    item_id,
    items_for,
    judge,
    replacements,
)


async def _judge_all(items, cap: float, legacy: int | None):
    if legacy is None:
        return await judge(items, max_cost_usd=cap)
    # free: everything at the old limit is cached; keep only fully judged items from it
    try:
        await judge(items, max_cost_usd=0.05, max_output_tokens=legacy)
        bad: set[str] = set()
    except SupportJudgingIncomplete as exc:
        bad = set(exc.refs)
    cached = await judge(items, max_cost_usd=0.05, max_output_tokens=legacy, strict=False)
    keep = [v for v in cached if v.citation_ref not in bad]
    redo = [i for i in items if i.id in {item_id(r) for r in bad}]
    print(f"cached: {len({v.citation_ref for v in keep})} items; judging {len(redo)} again")
    return keep + await judge(redo, max_cost_usd=cap)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study", type=Path)
    ap.add_argument("--max-cost", type=float, required=True)
    ap.add_argument(
        "--record-unjudged",
        action="store_true",
        help="after a retry, record items EvalKit still cannot judge as unjudged (not unsupported)",
    )
    ap.add_argument(
        "--legacy-tokens",
        type=int,
        default=None,
        help="first reread items already judged at this output limit from the cache (free), "
        "then judge only the rest at the current limit",
    )
    a = ap.parse_args()
    base = a.study
    cfg = load_study_config(base / "study.yaml")
    qs = load_questions(base / cfg.questions_path, cfg)
    data = base / "data"
    pages = [
        json.loads(x)
        for x in (data / "page_meta.jsonl").read_text(encoding="utf-8").splitlines()
        if x
    ]
    ok = {p["url"] for p in pages if p["outcome"] == "ok"}
    final, log = replacements(read_sample(base), ok, cache_dir=body_cache_dir())
    cites = [
        json.loads(x)
        for x in (data / "citations.jsonl").read_text(encoding="utf-8").splitlines()
        if x
    ]
    items = items_for(final, cites, qs, body_cache_dir())
    (data / "support_replacements.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in log), encoding="utf-8", newline="\n"
    )
    load_dotenv(Path(".env"))
    load_dotenv(base / ".env")
    unjudged: list[str] = []
    try:
        verdicts = asyncio.run(_judge_all(items, a.max_cost, a.legacy_tokens))
    except SupportJudgingIncomplete as exc:
        if not a.record_unjudged:
            raise
        # items that fail again after a retry are recorded as unjudged, never as unsupported
        unjudged = sorted(exc.refs)
        everything = asyncio.run(judge(items, max_cost_usd=0.05, strict=False))
        verdicts = [v for v in everything if v.citation_ref not in set(unjudged)]
    (data / "support_unjudged.jsonl").write_text(
        "".join(json.dumps({"citation_ref": r}) + "\n" for r in unjudged),
        encoding="utf-8",
        newline="\n",
    )
    (data / "support_verdicts.jsonl").write_text(
        "".join(v.model_dump_json() + "\n" for v in verdicts), encoding="utf-8", newline="\n"
    )
    by = {}
    for v in verdicts:
        by.setdefault(v.judge, [0, 0])
        by[v.judge][0] += v.verdict == "supported"
        by[v.judge][1] += 1
    print(
        f"judged {len(items) - len(unjudged)}/{len(items)} citations ({len(unjudged)} unjudged); "
        + "; ".join(f"{j}: {s}/{n} supported" for j, (s, n) in by.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
