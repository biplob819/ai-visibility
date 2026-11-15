"""Run the ask stage: interleaved, resumable, under a running spend cap (ASK-04, ASK-06, ASK-07).

For every question both models are asked concurrently, and question order is a seeded shuffle
per run, so the two models see the same web (D-9). Each verbatim response is stored before
anything is parsed (D-2); a completed key is never asked again, so a rerun calls only what is
missing. Spend is reserved before each call and settled after it, and a call that could push
spent + reserved past the cap is never made (EvalKit L-12, L-14).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import random
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from citewatch.cost import ASSUMPTIONS, Price, answer_cost, price_for
from citewatch.ledger import Ledger, check_money
from citewatch.schemas import StudyConfig, StudyQuestion, provider_of
from citewatch.store import RawStore, canonical_json, stage_key

from .base import Answer, Runner, TransportError, instruction, prompt_hash

ASK_CODE_VERSION = "ask-1"


def config_hash(cfg: StudyConfig) -> str:
    return hashlib.sha256(canonical_json(cfg.model_dump(mode="json"))).hexdigest()[:16]


def question_order(questions: Sequence[StudyQuestion], seed: int, run: int) -> list[StudyQuestion]:
    order = sorted(questions, key=lambda q: q.id)
    random.Random(f"{seed}:{run}").shuffle(order)
    return order


def ask_key(cfg: StudyConfig, run: int, question_id: str, model: str) -> str:
    unit = {"run": run, "question_id": question_id, "model": model}
    return stage_key("ask", ASK_CODE_VERSION, unit, config_hash(cfg), prompt_hash(instruction(cfg)))


@dataclass
class RunResult:
    asked: int = 0
    cached: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    stopped_at_cap: bool = False
    skipped_for_cap: int = 0
    spent_usd: float = 0.0
    order: list[str] = field(default_factory=list)


class SpendCap:
    """Reserve before a call, settle after; a reservation that would pass the cap is refused."""

    def __init__(self, cap_usd: float | None) -> None:
        self.cap = None if cap_usd is None else check_money(cap_usd, "cap_usd")
        self.spent = 0.0
        self.reserved = 0.0
        self._lock = threading.Lock()

    def reserve(self, est: float) -> bool:
        est = check_money(est, "estimate")
        with self._lock:
            if self.cap is not None and self.spent + self.reserved + est > self.cap:
                return False
            self.reserved += est
            return True

    def settle(self, est: float, actual: float) -> None:
        actual = check_money(actual, "actual")
        with self._lock:
            self.reserved = max(0.0, self.reserved - est)
            self.spent += actual


def envelope(
    answer: Answer,
    *,
    run: int,
    question: StudyQuestion,
    cost_usd: float,
    latency_ms: int,
    answered_at: str,
    cfg: StudyConfig,
) -> dict[str, Any]:
    body = asdict(answer)
    return {
        "schema_version": "1.0",
        "run": run,
        "question_id": question.id,
        "model": answer.model,
        "answered_at": answered_at,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "prompt_hash": prompt_hash(instruction(cfg)),
        "config_hash": config_hash(cfg),
        "answer": body,
    }


def ask_run(
    questions: Sequence[StudyQuestion],
    cfg: StudyConfig,
    *,
    run: int,
    runners: Mapping[str, Runner],
    store: RawStore,
    ledger: Ledger,
    prices: Mapping[str, Price],
    cap_usd: float | None,
    per_provider: int = 4,
    clock: Any = None,
) -> RunResult:
    clock = clock or (lambda: dt.datetime.now(dt.UTC))
    result = RunResult()
    cap = SpendCap(cap_usd)
    order = question_order(questions, cfg.seeds["order"], run)
    result.order = [q.id for q in order]
    sems = {p: threading.Semaphore(per_provider) for p in {provider_of(m) for m in cfg.models}}
    est_one = {
        m: answer_cost(
            price_for(m, prices),
            tokens_in=ASSUMPTIONS["tokens_in"],
            tokens_out=ASSUMPTIONS["tokens_out"],
            searches=ASSUMPTIONS["searches"],
        )
        for m in cfg.models
    }
    lock = threading.Lock()

    def one(q: StudyQuestion, model: str) -> None:
        key = ask_key(cfg, run, q.id, model)
        if store.has("ask", key):
            with lock:
                result.cached += 1
            ledger.event(
                "ask",
                key,
                cache_hit=True,
                latency_ms=0,
                cost_usd=0.0,
                question_id=q.id,
                model=model,
            )
            return
        est = est_one[model]
        if not cap.reserve(est):
            with lock:
                result.stopped_at_cap = True
                result.skipped_for_cap += 1
            return
        actual = 0.0
        with sems[provider_of(model)]:
            start = time.monotonic()
            try:
                answer = runners[model].ask(q, cfg)
            except TransportError as exc:
                cap.settle(est, 0.0)
                with lock:
                    result.errors.append(
                        {
                            "question_id": q.id,
                            "model": model,
                            "error": "transport",
                            "detail": str(exc),
                        }
                    )
                ledger.event(
                    "ask",
                    key,
                    cache_hit=False,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    cost_usd=0.0,
                    error="transport",
                    question_id=q.id,
                    model=model,
                )
                return
            except Exception:
                cap.settle(est, 0.0)
                raise
            latency = int((time.monotonic() - start) * 1000)
        actual = answer_cost(
            price_for(model, prices),
            tokens_in=answer.tokens_in,
            tokens_out=answer.tokens_out,
            cached_in=answer.cached_in,
            searches=answer.searches,
        )
        cap.settle(est, actual)
        answered_at = clock().isoformat(timespec="seconds").replace("+00:00", "Z")
        store.put(
            "ask",
            key,
            envelope(
                answer,
                run=run,
                question=q,
                cost_usd=actual,
                latency_ms=latency,
                answered_at=answered_at,
                cfg=cfg,
            ),
        )
        ledger.event(
            "ask",
            key,
            cache_hit=False,
            latency_ms=latency,
            cost_usd=actual,
            question_id=q.id,
            model=model,
            refusal=answer.refusal,
            searches=answer.searches,
        )
        with lock:
            result.asked += 1

    workers = max(1, per_provider * len(sems))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, q, m) for q in order for m in cfg.models]  # models side by side
        for f in futures:
            f.result()  # re-raise anything unexpected (config errors, bugs)
    result.spent_usd = round(cap.spent, 6)
    return result
