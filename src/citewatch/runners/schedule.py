"""Run the ask stage: interleaved, resumable, under a running spend cap (ASK-04..07).

For every question both models are asked side by side, in a seeded order per run (D-9).

The order of work for each paid call never changes:
  1. the call returns verbatim responses (nothing parsed);
  2. its cost is read from usage and appended to the spend ledger at once (OWNER D-19), so no
     later failure or interrupt can lose a dollar;
  3. the verbatim responses are stored (D-2); parsing happens later, in extract.

Every per-call failure is caught and recorded, never allowed to stop the other calls. Ctrl-C
cancels the queued calls and lets only those already in flight finish. Spend is reserved
before each call and settled after it; the reservation starts at four times the planning
estimate and becomes the largest real cost seen so far, so the cap is passed by at most the
in-flight calls' excess over that (D-37). A call refused only because other calls hold
reservations waits for them to settle; it is skipped only when money already spent leaves no room.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import random
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from citewatch.cost import ASSUMPTIONS, Price, answer_cost, price_for, record_spend
from citewatch.ledger import Ledger, check_money
from citewatch.schemas import StudyConfig, StudyQuestion, provider_of
from citewatch.store import RawStore, canonical_json, stage_key

from .base import RawCall, Runner, TransportError, instruction, prompt_hash

ASK_CODE_VERSION = "ask-3"  # ask-3: the question text is in the key
INITIAL_RESERVE_FACTOR = 4
STOP_MODEL_AFTER = {401, 403}  # a bad key or a refused account: stop asking that model
_STOP_KINDS = {f"provider:{s}" for s in STOP_MODEL_AFTER}


def answer_config_hash(cfg: StudyConfig) -> str:
    """Only the settings that change an answer. Budget, contact, seeds and other fields can be
    edited without re-asking anything already stored (H2)."""
    relevant = {
        "effort": cfg.effort,
        "max_searches": cfg.max_searches,
        "word_limit": cfg.word_limit,
        "user_location": cfg.user_location.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(relevant)).hexdigest()[:16]


def config_hash(cfg: StudyConfig) -> str:
    """The whole study config, for the run manifest (not part of any store key)."""
    return hashlib.sha256(canonical_json(cfg.model_dump(mode="json"))).hexdigest()[:16]


def question_order(questions: Sequence[StudyQuestion], seed: int, run: int) -> list[StudyQuestion]:
    order = sorted(questions, key=lambda q: q.id)
    random.Random(f"{seed}:{run}").shuffle(order)
    return order


def ask_key(cfg: StudyConfig, run: int, question: StudyQuestion, model: str) -> str:
    """Editing a question's text asks it again, even under the same id (N1.2 v2 M4)."""
    text_sha = hashlib.sha256(question.text.encode("utf-8")).hexdigest()[:16]
    unit = {"run": run, "question_id": question.id, "text_sha": text_sha, "model": model}
    return stage_key(
        "ask", ASK_CODE_VERSION, unit, answer_config_hash(cfg), prompt_hash(instruction(cfg))
    )


@dataclass
class RunResult:
    asked: int = 0
    cached: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    stopped_at_cap: bool = False
    skipped_for_cap: int = 0
    interrupted: bool = False
    cancelled: int = 0
    spent_usd: float = 0.0
    order: list[str] = field(default_factory=list)


class SpendCap:
    """Reserve before a call, settle after; a reservation that would pass the cap is refused.
    The reservation per call adapts upward to the largest real cost seen (D-37)."""

    def __init__(self, cap_usd: float | None, initial_reserve: float) -> None:
        self.cap = None if cap_usd is None else check_money(cap_usd, "cap_usd")
        self.reserve_each = check_money(initial_reserve, "reserve")
        self.max_seen = 0.0
        self.spent = 0.0
        self.reserved = 0.0
        self._cond = threading.Condition()

    def _try(self) -> float | None:
        est = self.reserve_each
        if self.cap is not None and self.spent + self.reserved + est > self.cap:
            return None
        self.reserved += est
        return est

    def reserve(self) -> float | None:
        """The amount reserved, or None when the call would pass the cap right now."""
        with self._cond:
            return self._try()

    def reserve_wait(self, stop: threading.Event, poll: float = 0.2) -> float | None:
        """Reserve, waiting while other calls' reservations are what blocks it (N1.2 v2 M2).
        None only when spent money alone leaves no room, or on stop."""
        with self._cond:
            while True:
                got = self._try()
                if got is not None:
                    return got
                if self.reserved <= 0 or stop.is_set():
                    return None
                self._cond.wait(poll)

    def settle(self, reserved: float, actual: float) -> None:
        actual = check_money(actual, "actual")
        with self._cond:
            self.reserved = max(0.0, self.reserved - reserved)
            self.spent += actual
            if actual > self.max_seen:
                self.max_seen = actual
                self.reserve_each = actual  # never reserve less than the worst real call so far
            self._cond.notify_all()


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
    spend_ledger: Path | None = None,
    per_provider: int = 4,
    clock: Any = None,
    stop: threading.Event | None = None,
) -> RunResult:
    clock = clock or (lambda: dt.datetime.now(dt.UTC))
    stop = stop or threading.Event()
    result = RunResult()
    order = question_order(questions, cfg.seeds["order"], run)
    result.order = [q.id for q in order]
    planning = max(
        answer_cost(
            price_for(m, prices),
            tokens_in=ASSUMPTIONS["tokens_in"],
            tokens_out=ASSUMPTIONS["tokens_out"],
            searches=ASSUMPTIONS["searches"],
        )
        for m in cfg.models
    )
    cap = SpendCap(cap_usd, planning * INITIAL_RESERVE_FACTOR)
    sems = {p: threading.Semaphore(per_provider) for p in {provider_of(m) for m in cfg.models}}
    stopped_models: set[str] = set()
    lock = threading.Lock()

    def note_error(
        q: StudyQuestion, model: str, kind: str, detail: str, key: str, cost: float = 0.0
    ) -> None:
        with lock:
            result.errors.append(
                {
                    "question_id": q.id,
                    "model": model,
                    "error": kind,
                    "detail": detail[:300],
                    "cost_usd": cost,
                }
            )
        ledger.event(
            "ask",
            key,
            cache_hit=False,
            latency_ms=0,
            cost_usd=cost,
            error=kind,
            question_id=q.id,
            model=model,
        )

    def one(q: StudyQuestion, model: str) -> None:
        key = ask_key(cfg, run, q, model)
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
        if stop.is_set() or model in stopped_models:
            with lock:
                result.cancelled += 1
            return
        reserved = cap.reserve_wait(stop)
        if reserved is None:
            with lock:
                if stop.is_set():
                    result.cancelled += 1
                else:
                    result.stopped_at_cap = True
                    result.skipped_for_cap += 1
            return
        runner = runners[model]
        with sems[provider_of(model)]:
            # a worker may have waited for this slot: check again so Ctrl-C or a bad key
            # starts nothing new (N1.2 v2 M1)
            if stop.is_set() or model in stopped_models:
                cap.settle(reserved, 0.0)
                with lock:
                    result.cancelled += 1
                return
            start = time.monotonic()
            try:
                rc: RawCall = runner.call(q, cfg)
            except TransportError as exc:
                cap.settle(reserved, 0.0)
                note_error(q, model, "transport", str(exc), key)
                return
            except Exception as exc:  # a provider refusal of the request, a bad key, a bug
                cap.settle(reserved, 0.0)
                status = getattr(exc, "status_code", None)
                if status in STOP_MODEL_AFTER:
                    stopped_models.add(model)
                kind = (
                    f"provider:{status}"
                    if isinstance(status, int)
                    else f"internal:{type(exc).__name__}"
                )
                note_error(q, model, kind, str(exc), key)
                return
            latency = int((time.monotonic() - start) * 1000)
            if rc.error is not None and rc.error.split(" during", 1)[0] in _STOP_KINDS:
                stopped_models.add(model)  # before the slot is released, so no waiter starts
        # 2. cost first, written down at once
        try:
            u = runner.usage(rc.responses)
            if not (u.tokens_in or u.tokens_out):
                raise ValueError("a paid response reported no tokens")
            actual = answer_cost(
                price_for(model, prices),
                tokens_in=u.tokens_in,
                tokens_out=u.tokens_out,
                cached_in=u.cached_in,
                searches=u.searches,
            )
        except Exception as exc:  # cannot price it: charge the reservation so the cap stays safe
            actual = reserved
            u = None
            note_error(q, model, "unpriced", f"{type(exc).__name__}: {exc}", key, cost=actual)
        cap.settle(reserved, actual)
        if spend_ledger is not None:
            try:
                record_spend(
                    spend_ledger,
                    kind="answer",
                    run_id=f"{cfg.name}:run-{run}",
                    spent_usd=actual,
                    note=f"{q.id} {model}",
                )
            except OSError as exc:  # keep the paid response even if the spend file fails
                note_error(
                    q, model, "spend-ledger", f"{type(exc).__name__}: {exc}", key, cost=actual
                )
        answered_at = clock().isoformat(timespec="seconds").replace("+00:00", "Z")
        env = {
            "schema_version": "1.0",
            "run": run,
            "question_id": q.id,
            "model": model,
            "answered_at": answered_at,
            "latency_ms": latency,
            "cost_usd": actual,
            "usage": None if u is None else u.__dict__,
            "prompt_hash": prompt_hash(instruction(cfg)),
            "answer_config_hash": answer_config_hash(cfg),
            "request": rc.request,
            "responses": rc.responses,
            "error": rc.error,
        }
        # 3. store the verbatim responses; a partial (failed continuation) is kept for the
        # record under its own stage and the question is asked again on resume
        stage = "ask" if rc.error is None else "ask_partial"
        try:
            store.put(stage, key, env)
        except Exception as exc:
            note_error(q, model, "store", f"{type(exc).__name__}: {exc}", key, cost=actual)
            return
        if rc.error is not None:
            kind = rc.error.split(" during", 1)[0]
            note_error(q, model, kind, rc.error, key, cost=actual)
            return
        ledger.event(
            "ask",
            key,
            cache_hit=False,
            latency_ms=latency,
            cost_usd=actual,
            question_id=q.id,
            model=model,
        )
        with lock:
            result.asked += 1

    workers = max(1, per_provider * len(sems))
    pool = ThreadPoolExecutor(max_workers=workers)
    futures: list[Future[None]] = [pool.submit(one, q, m) for q in order for m in cfg.models]
    try:
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            for f in done:
                f.result()  # one() catches per-call errors; anything here is a bug
    except KeyboardInterrupt:
        stop.set()
        result.interrupted = True
        pool.shutdown(wait=True, cancel_futures=True)  # in-flight calls finish, queued are dropped
        result.cancelled += sum(1 for f in futures if f.cancelled())
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        result.spent_usd = round(cap.spent, 6)
    return result
