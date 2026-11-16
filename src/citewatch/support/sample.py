"""SUP-01: the seeded, stratified support sample, drawn after run 1's extract and before its
fetch so the fetcher keeps those pages' main text (Tech Spec §8.1).

50 citations: 25 per model, 5 per model × intent, plus 2 reserves per stratum. A citation is a
(run, question, model, ordinal) row of `citations.jsonl` with a non-empty answer span (the claim).
The draw is written once and never redrawn: a second call returns the stored sample.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from citewatch.schemas import StudyConfig, StudyQuestion

SAMPLE_FILE = "support_sample.jsonl"
PER_STRATUM = 5
RESERVES = 2


def citation_ref(row: dict[str, Any]) -> str:
    return f"{row['run']}:{row['question_id']}:{row['model']}:{row['ordinal']}"


def draw_sample(
    citations: Sequence[dict[str, Any]],
    cfg: StudyConfig,
    questions: Sequence[StudyQuestion],
    run: int = 1,
    per_stratum: int = PER_STRATUM,
    reserves: int = RESERVES,
) -> list[dict[str, Any]]:
    intent_of = {q.id: q.intent for q in questions}
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in citations:
        if c["run"] != run or not (c.get("answer_span") or "").strip():
            continue
        intent = intent_of.get(c["question_id"])
        if intent is not None and c["model"] in cfg.models:
            strata[(c["model"], intent)].append(c)
    rng = random.Random(cfg.seeds["support_sample"])
    out: list[dict[str, Any]] = []
    for model in sorted(cfg.models):
        for intent in sorted(cfg.intents):
            pool = sorted(strata[(model, intent)], key=citation_ref)
            picked = rng.sample(pool, min(len(pool), per_stratum + reserves))
            for rank, c in enumerate(picked):
                out.append(
                    {
                        "citation_ref": citation_ref(c),
                        "url": c["url"],
                        "model": model,
                        "intent": intent,
                        "question_id": c["question_id"],
                        "rank": rank,
                        "role": "sample" if rank < per_stratum else "reserve",
                        "seed": cfg.seeds["support_sample"],
                    }
                )
    return out


def read_sample(base: Path) -> list[dict[str, Any]]:
    p = base / "data" / SAMPLE_FILE
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_sample(base: Path, rows: Sequence[dict[str, Any]]) -> Path:
    """Write the sample once; an existing sample is never replaced (it fixes which pages keep
    their text, and redrawing after seeing results would be a forking path)."""
    p = base / "data" / SAMPLE_FILE
    if p.is_file():
        raise FileExistsError(f"{p} already exists; the support sample is drawn once")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8", newline="\n"
    )
    return p
