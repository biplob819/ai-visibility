#!/usr/bin/env python3
"""Record real provider responses as test fixtures (N1.2, ASK-08). Costs about $0.40.

Asks two questions on both flagship models with the flagship settings, writes each verbatim
answer envelope to tests/fixtures/providers/, and appends one spend line per paid call to the
flagship's spend ledger the moment the call returns, before anything is parsed (L-27, N1.2 v2
M3), so a later failure never loses the record of money spent. Never prints a key. Run only with
the owner's approval of the spend.
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
from citewatch.runners import anthropic_runner, make_runner, openai_runner  # noqa: E402
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
    spend_file = ROOT / "studies" / "uk-health" / "data" / "spend-ledger.jsonl"
    models = [m for m in cfg.models if not sys.argv[1:] or m in sys.argv[1:]]
    for model in models:
        runner = make_runner(model)
        for q in QUESTIONS:
            start = time.monotonic()
            rc = runner.call(q, cfg)
            latency = int((time.monotonic() - start) * 1000)
            try:  # cost first, written down at once
                u = runner.usage(rc.responses)
                cost = answer_cost(
                    prices[model],
                    tokens_in=u.tokens_in,
                    tokens_out=u.tokens_out,
                    cached_in=u.cached_in,
                    searches=u.searches,
                )
            except Exception as exc:  # unpriceable: write a generous estimate, never nothing
                cost = 4 * answer_cost(
                    prices[model], tokens_in=25_000, tokens_out=1_500, searches=3
                )
                print(f"{model} {q.id}: could not price ({exc}); recording ${cost:.4f}")
            record_spend(
                spend_file,
                kind="fixtures",
                run_id="n1.2-fixtures",
                spent_usd=cost,
                note=f"{q.id} {model}",
            )
            total += cost
            if model.startswith("claude"):
                answer = anthropic_runner.parse(model, rc.responses, rc.request)
            else:
                answer = openai_runner.parse(model, rc.responses[0], rc.request)
            from dataclasses import asdict

            env = {
                "schema_version": "1.0",
                "run": 0,
                "question_id": q.id,
                "model": model,
                "answered_at": dt.datetime.now(dt.UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "latency_ms": latency,
                "cost_usd": cost,
                "answer": asdict(answer),
            }
            path = out / f"{model}--{q.id}.json"
            path.write_text(
                json.dumps(env, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(
                f"{model} {q.id}: {answer.stop_reason}, {answer.searches} searches, "
                f"{len(answer.answer_text.split())} words, ${cost:.4f} -> {path.name}"
            )
    print(f"total ${total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
