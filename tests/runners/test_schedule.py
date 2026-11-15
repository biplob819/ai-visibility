import json
import threading
import time

import pytest

from citewatch.cost import load_prices
from citewatch.ledger import Ledger
from citewatch.runners.base import RawCall, TransportError, Usage
from citewatch.runners.schedule import (
    INITIAL_RESERVE_FACTOR,
    SpendCap,
    answer_config_hash,
    ask_key,
    ask_run,
    question_order,
)
from citewatch.schemas import StudyQuestion
from citewatch.store import RawStore

from .helpers import CFG, StatusError

QS = [
    StudyQuestion(id=f"v-{i:03d}", text=f"Question {i}?", intent="fitness", time_sensitive=False)
    for i in range(1, 7)
]
PRICES = load_prices()


class FakeRunner:
    """Returns a RawCall with a usage block; tokens decide the cost."""

    def __init__(self, model, fail=None, delay=0.0, tokens_in=20000, tokens_out=500, partial=()):
        self.model = model
        self.provider = "anthropic" if model.startswith("claude") else "openai"
        self.fail = fail or {}
        self.delay, self.tokens_in, self.tokens_out = delay, tokens_in, tokens_out
        self.partial = set(partial)
        self.calls: list[str] = []
        self.live = self.max_live = 0
        self._lock = threading.Lock()

    def call(self, q, cfg):
        with self._lock:
            self.live += 1
            self.max_live = max(self.max_live, self.live)
            self.calls.append(q.id)
        try:
            time.sleep(self.delay)
            if q.id in self.fail:
                raise self.fail[q.id]
            resp = {"id": q.id, "usage": {"in": self.tokens_in, "out": self.tokens_out}}
            err = "transport during continuation" if q.id in self.partial else None
            return RawCall(self.model, {"q": q.id}, [resp], error=err)
        finally:
            with self._lock:
                self.live -= 1

    def usage(self, responses):
        u = responses[-1]["usage"]
        return Usage(u["in"], u["out"], 0, 1)


def runners(**kw):
    return {m: FakeRunner(m, **kw) for m in CFG.models}


def go(tmp_path, rs, run=1, cap=None, qs=QS, per_provider=4, cfg=CFG, stop=None):
    return ask_run(
        qs,
        cfg,
        run=run,
        runners=rs,
        store=RawStore(tmp_path),
        ledger=Ledger(tmp_path / "log"),
        prices=PRICES,
        cap_usd=cap,
        per_provider=per_provider,
        spend_ledger=tmp_path / "spend.jsonl",
        stop=stop,
    )


def spend_lines(tmp_path):
    p = tmp_path / "spend.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_every_question_is_asked_on_both_models_and_stored_verbatim(tmp_path):
    res = go(tmp_path, runners())
    assert res.asked == 12 and res.cached == 0 and not res.errors
    store = RawStore(tmp_path)
    for q in QS:
        for m in CFG.models:
            env = store.get("ask", ask_key(CFG, 1, q.id, m))
            assert env["question_id"] == q.id and env["model"] == m
            assert env["responses"] == [{"id": q.id, "usage": {"in": 20000, "out": 500}}]
            assert env["answered_at"].endswith("Z") and env["cost_usd"] > 0
    assert len(spend_lines(tmp_path)) == 12  # one spend line per paid call


def test_a_completed_run_makes_no_calls_and_a_new_run_asks_again(tmp_path):
    go(tmp_path, runners())
    again = runners()
    res = go(tmp_path, again)
    assert res.asked == 0 and res.cached == 12 and all(not r.calls for r in again.values())
    assert go(tmp_path, runners(), run=2).asked == 12  # run 2 is never served from run 1


def test_editing_budget_contact_or_seeds_reasks_nothing(tmp_path):
    go(tmp_path, runners())
    edited = CFG.model_copy(
        update={
            "max_cost_usd": 99.0,
            "user_agent": "citewatch/0.2 (+https://github.com/x/y)",
            "name": "renamed",
            "stale_days": 30,
        }
    )
    assert answer_config_hash(edited) == answer_config_hash(CFG)
    res = go(tmp_path, runners(), cfg=edited)
    assert res.asked == 0 and res.cached == 12
    changed = CFG.model_copy(update={"effort": "high"})
    assert go(tmp_path, runners(), cfg=changed).asked == 12  # an answer-changing edit re-asks


def test_errors_in_one_call_never_stop_the_others(tmp_path):
    fail = {"v-002": TransportError("gone"), "v-003": StatusError(400), "v-004": KeyError("bug")}
    rs = runners(fail=fail)
    res = go(tmp_path, rs)
    assert res.asked == 6 and len(res.errors) == 6
    kinds = {e["error"] for e in res.errors}
    assert kinds == {"transport", "provider:400", "internal:KeyError"}
    retry = go(tmp_path, runners())
    assert retry.asked == 6 and retry.cached == 6  # resume asks only what failed


def test_a_bad_key_stops_that_model_only(tmp_path):
    fail = {q.id: StatusError(401) for q in QS}
    rs = {
        CFG.models[0]: FakeRunner(CFG.models[0], fail=fail),
        CFG.models[1]: FakeRunner(CFG.models[1]),
    }
    res = go(tmp_path, rs, per_provider=1)
    assert res.asked == 6 and len(rs[CFG.models[0]].calls) < 6 and res.cancelled > 0


def test_spend_is_recorded_even_when_storing_fails(tmp_path, monkeypatch):
    def broken_put(self, stage, key, obj):
        raise OSError("no space left on device")

    monkeypatch.setattr(RawStore, "put", broken_put)
    res = go(tmp_path, runners())
    assert res.asked == 0 and {e["error"] for e in res.errors} == {"store"}
    lines = spend_lines(tmp_path)
    assert len(lines) == 12 and round(sum(x["spent_usd"] for x in lines), 6) == res.spent_usd > 0


def test_an_unpriceable_response_is_charged_its_reservation(tmp_path):
    class Odd(FakeRunner):
        def usage(self, responses):
            raise ValueError("unexpected usage shape")

    rs = {m: Odd(m) for m in CFG.models}
    res = go(tmp_path, rs, qs=QS[:1])
    assert {e["error"] for e in res.errors} == {"unpriced"} and res.spent_usd > 0
    assert len(spend_lines(tmp_path)) == 2
    assert RawStore(tmp_path).has("ask", ask_key(CFG, 1, "v-001", CFG.models[0]))  # raw kept


def test_a_failed_continuation_keeps_what_was_paid_and_asks_again(tmp_path):
    res = go(tmp_path, runners(partial={"v-001"}), qs=QS[:1])
    store = RawStore(tmp_path)
    key = ask_key(CFG, 1, "v-001", CFG.models[0])
    assert not store.has("ask", key) and store.has("ask_partial", key)
    assert {e["error"] for e in res.errors} == {"transport"} and len(spend_lines(tmp_path)) == 2
    assert go(tmp_path, runners(), qs=QS[:1]).asked == 2


def test_question_order_is_seeded_per_run_and_both_models_go_side_by_side(tmp_path):
    a = [q.id for q in question_order(QS, 7, 1)]
    assert a == [q.id for q in question_order(list(reversed(QS)), 7, 1)]
    assert a != [q.id for q in question_order(QS, 7, 2)]
    rs = runners(delay=0.01)
    res = go(tmp_path, rs, per_provider=1)
    assert res.order == [q.id for q in question_order(QS, CFG.seeds["order"], 1)]
    assert rs[CFG.models[0]].calls == res.order == rs[CFG.models[1]].calls


def test_per_provider_concurrency_limit_holds_and_is_used(tmp_path):
    rs = runners(delay=0.05)
    go(tmp_path, rs, per_provider=2)
    assert all(r.max_live == 2 for r in rs.values())


def test_the_cap_holds_even_when_calls_cost_far_more_than_planned(tmp_path):
    # each call costs about 10x the planning estimate
    rs = runners(tokens_in=400_000, tokens_out=8000)
    res = go(tmp_path, rs, cap=1.0, per_provider=4)
    assert res.stopped_at_cap
    planning = 0.095
    in_flight_bound = 8 * planning * INITIAL_RESERVE_FACTOR
    assert res.spent_usd <= 1.0 + in_flight_bound
    assert res.spent_usd < 3.0  # the old fixed reservation spent $3.00 against a $0.50 cap


def test_spend_cap_reservation_adapts_to_the_worst_real_call():
    cap = SpendCap(1.0, initial_reserve=0.2)
    r1 = cap.reserve()
    assert r1 == 0.2
    assert r1 is not None
    cap.settle(r1, 0.6)
    assert cap.reserve_each == 0.6 and cap.reserve() is None  # 0.6 spent + 0.6 > 1.0
    with pytest.raises(ValueError):
        cap.settle(0.0, float("nan"))
    assert SpendCap(None, 1.0).reserve() == 1.0


def test_an_interrupt_stops_queued_calls_and_records_what_was_spent(tmp_path):
    stop = threading.Event()
    qs = [
        StudyQuestion(id=f"v-{i:03d}", text="Q?", intent="fitness", time_sensitive=False)
        for i in range(1, 41)
    ]
    rs = runners(delay=0.05)
    timer = threading.Timer(0.12, stop.set)
    timer.start()
    res = go(tmp_path, rs, qs=qs, per_provider=2, stop=stop)
    timer.cancel()
    made = sum(len(r.calls) for r in rs.values())
    assert made < 80 and res.cancelled == 80 - made
    assert len(spend_lines(tmp_path)) == made == res.asked


def test_keyboard_interrupt_in_the_main_loop_cancels_queued_calls(tmp_path, monkeypatch):
    import concurrent.futures

    real_wait = concurrent.futures.wait
    calls = {"n": 0}

    def wait_then_interrupt(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real_wait(*a, **k)

    monkeypatch.setattr("citewatch.runners.schedule.wait", wait_then_interrupt)
    qs = [
        StudyQuestion(id=f"v-{i:03d}", text="Q?", intent="fitness", time_sensitive=False)
        for i in range(1, 41)
    ]
    rs = runners(delay=0.05)
    res = go(tmp_path, rs, qs=qs, per_provider=1)
    made = sum(len(r.calls) for r in rs.values())
    assert res.interrupted and made < 80
    assert len(spend_lines(tmp_path)) == res.asked == made
