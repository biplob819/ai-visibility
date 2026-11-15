import threading
import time

import pytest

from citewatch.cost import load_prices
from citewatch.ledger import Ledger
from citewatch.runners.base import Answer, TransportError
from citewatch.runners.schedule import SpendCap, ask_key, ask_run, question_order
from citewatch.schemas import StudyQuestion
from citewatch.store import RawStore

from .helpers import CFG

QS = [
    StudyQuestion(id=f"v-{i:03d}", text=f"Question {i}?", intent="fitness", time_sensitive=False)
    for i in range(1, 7)
]
PRICES = load_prices()


class FakeRunner:
    def __init__(self, model, fail_ids=(), delay=0.0):
        self.model, self.provider = model, ("anthropic" if model.startswith("claude") else "openai")
        self.fail_ids, self.delay = set(fail_ids), delay
        self.asked: list[str] = []
        self.live = 0
        self.max_live = 0
        self._lock = threading.Lock()

    def ask(self, q, cfg):
        with self._lock:
            self.live += 1
            self.max_live = max(self.max_live, self.live)
        try:
            time.sleep(self.delay)
            if q.id in self.fail_ids:
                raise TransportError("planted")
            self.asked.append(q.id)
            return Answer(
                model=self.model,
                model_snapshot=self.model,
                answer_text=f"answer to {q.id}",
                stop_reason="end_turn",
                refusal=False,
                refusal_category=None,
                searches=1,
                search_actions=["search"],
                search_errors=[],
                tokens_in=20000,
                tokens_out=500,
                cached_in=0,
                continuations=0,
                raw=[{"id": q.id}],
                request={},
            )
        finally:
            with self._lock:
                self.live -= 1


def runners(**kw):
    return {m: FakeRunner(m, **kw) for m in CFG.models}


def go(tmp_path, rs, run=1, cap=None, qs=QS, per_provider=4):
    return ask_run(
        qs,
        CFG,
        run=run,
        runners=rs,
        store=RawStore(tmp_path),
        ledger=Ledger(tmp_path / "log"),
        prices=PRICES,
        cap_usd=cap,
        per_provider=per_provider,
    )


def test_every_question_is_asked_on_both_models_and_stored(tmp_path):
    rs = runners()
    res = go(tmp_path, rs)
    assert res.asked == 12 and res.cached == 0 and not res.errors
    store = RawStore(tmp_path)
    for q in QS:
        for m in CFG.models:
            env = store.get("ask", ask_key(CFG, 1, q.id, m))
            assert (
                env["question_id"] == q.id
                and env["model"] == m
                and env["answer"]["raw"] == [{"id": q.id}]
            )
            assert env["answered_at"].endswith("Z") and env["cost_usd"] > 0


def test_a_completed_run_makes_no_calls_and_a_new_run_asks_again(tmp_path):
    go(tmp_path, runners())
    again = runners()
    res = go(tmp_path, again)
    assert res.asked == 0 and res.cached == 12 and all(not r.asked for r in again.values())
    run2 = go(tmp_path, runners(), run=2)
    assert run2.asked == 12  # run 2 is never served from run 1


def test_an_interrupted_run_resumes_with_only_the_missing_keys(tmp_path):
    first = go(tmp_path, runners(fail_ids={"v-002", "v-005"}))
    assert first.asked == 8 and len(first.errors) == 4
    assert all(e["error"] == "transport" for e in first.errors)
    retry = runners()
    res = go(tmp_path, retry)
    assert res.asked == 4 and res.cached == 8
    assert sorted(retry["claude-sonnet-5-5"].asked) == ["v-002", "v-005"]


def test_question_order_is_seeded_per_run_and_recorded(tmp_path):
    a = [q.id for q in question_order(QS, 7, 1)]
    assert a == [q.id for q in question_order(list(reversed(QS)), 7, 1)]
    assert a != [q.id for q in question_order(QS, 7, 2)]
    res = go(tmp_path, runners())
    assert res.order == [q.id for q in question_order(QS, CFG.seeds["order"], 1)]


def test_per_provider_concurrency_limit_holds(tmp_path):
    rs = runners(delay=0.05)
    go(tmp_path, rs, per_provider=2)
    assert all(r.max_live <= 2 for r in rs.values())
    assert all(r.max_live == 2 for r in rs.values())  # and the limit is actually used


def test_the_cap_stops_new_calls_and_spend_stays_under_it(tmp_path):
    res = go(tmp_path, runners(), cap=0.5)
    assert res.stopped_at_cap and res.skipped_for_cap > 0
    assert res.spent_usd <= 0.5 and res.asked + res.skipped_for_cap == 12


def test_spend_cap_reservations():
    cap = SpendCap(1.0)
    assert cap.reserve(0.6) and not cap.reserve(0.6)
    cap.settle(0.6, 0.2)
    assert cap.reserve(0.6)
    with pytest.raises(ValueError):
        cap.reserve(float("nan"))
    assert SpendCap(None).reserve(1e9)


def test_unexpected_errors_propagate(tmp_path):
    class Broken(FakeRunner):
        def ask(self, q, cfg):
            raise KeyError("bug")

    rs = {m: Broken(m) for m in CFG.models}
    with pytest.raises(KeyError):
        go(tmp_path, rs)
