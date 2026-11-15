#!/usr/bin/env python3
"""Record real provider responses as test fixtures (N1.2, ASK-08). Costs about $0.40.

Asks two questions on both flagship models with the flagship settings, writes each verbatim
answer envelope to tests/fixtures/providers/, and appends the spend to the flagship's spend
ledger. Never prints a key. Run only with the owner's approval of the spend.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from citewatch.cost import answer_cost, load_prices, record_spend  # noqa: E402
from citewatch.env import load_dotenv  # noqa: E402
from citewatch.runners import make_runner  # noqa: E402
from citewatch.runners.schedule import envelope  # noqa: E402
from citewatch.schemas import StudyQuestion, load_study_config  # noqa: E402

QUESTIONS = [
    StudyQuestion(
        id="v-901",
        text="How much does an NHS prescription cost in England?",
        intent="nhs_services",
        time_sensitive=True,
        ts_reason="prices",
    ),
    StudyQuestion(
        id="v-902",
        text="Why do my legs ache the day after a long run?",
        intent="fitness",
        time_sensitive=False,
    ),
]


def main() -> int:
    load_dotenv(ROOT / ".env")
    cfg = load_study_config(ROOT / "studies" / "uk-health" / "study.yaml")
    prices = load_prices()
    out = ROOT / "tests" / "fixtures" / "providers"
    out.mkdir(parents=True, exist_ok=True)
    total = 0.0
    models = [m for m in cfg.models if not sys.argv[1:] or m in sys.argv[1:]]
    for model in models:
        runner = make_runner(model)
        for q in QUESTIONS:
            start = time.monotonic()
            answer = runner.ask(q, cfg)
            latency = int((time.monotonic() - start) * 1000)
            cost = answer_cost(
                prices[model],
                tokens_in=answer.tokens_in,
                tokens_out=answer.tokens_out,
                cached_in=answer.cached_in,
                searches=answer.searches,
            )
            total += cost
            env = envelope(
                answer,
                run=0,
                question=q,
                cost_usd=cost,
                latency_ms=latency,
                answered_at=dt.datetime.now(dt.UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                cfg=cfg,
            )
            path = out / f"{model}--{q.id}.json"
            path.write_text(
                json.dumps(env, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(
                f"{model} {q.id}: {answer.stop_reason}, {answer.searches} searches, "
                f"{len(answer.answer_text.split())} words, ${cost:.4f} -> {path.name}"
            )
    record_spend(
        ROOT / "studies" / "uk-health" / "data" / "spend-ledger.jsonl",
        kind="fixtures",
        run_id="n1.2-fixtures",
        spent_usd=total,
        note=f"N1.2 provider fixtures: 2 questions x {', '.join(models)}",
    )
    print(f"total ${total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
