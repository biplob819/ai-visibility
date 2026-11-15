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
            err = "transport during continuation: gone" if q.id in self.partial else None
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
            env = store.get("ask", ask_key(CFG, 1, q, m))
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
    assert RawStore(tmp_path).has("ask", ask_key(CFG, 1, QS[0], CFG.models[0]))  # raw kept


def test_a_failed_continuation_keeps_what_was_paid_and_asks_again(tmp_path):
    res = go(tmp_path, runners(partial={"v-001"}), qs=QS[:1])
    store = RawStore(tmp_path)
    key = ask_key(CFG, 1, QS[0], CFG.models[0])
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
    assert cap.reserve_each == 0.6
    assert cap.reserve() == pytest.approx(0.4)  # nothing in flight: reserve the room left (v3 M1)
    assert cap.reserve() is None  # 0.6 spent + 0.4 held + 0.6 > 1.0
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
    stop = threading.Event()
    res = go(tmp_path, rs, qs=qs, per_provider=1, stop=stop)
    made = sum(len(r.calls) for r in rs.values())
    assert res.interrupted and made < 80 and stop.is_set()  # workers see the stop (v3 M3)
    assert len(spend_lines(tmp_path)) == res.asked == made


def test_a_failing_spend_file_still_keeps_the_paid_response(tmp_path, monkeypatch):
    import citewatch.runners.schedule as sch

    def broken(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(sch, "record_spend", broken)
    res = go(tmp_path, runners(), qs=QS[:1])
    assert {e["error"] for e in res.errors} == {"spend-ledger"} and res.asked == 2
    assert RawStore(tmp_path).has("ask", ask_key(CFG, 1, QS[0], CFG.models[0]))


def test_a_failed_continuation_of_any_kind_keeps_what_was_paid(tmp_path):
    """N1.2 v2 H1: the real Claude runner, a paid paused turn, then a 400 on the continuation."""
    from citewatch.runners.anthropic_runner import AnthropicRunner

    from .helpers import FakeAnthropic, claude_raw

    paused = claude_raw()
    paused["stop_reason"] = "pause_turn"
    claude, gpt = CFG.models
    rs = {
        claude: AnthropicRunner(claude, client=FakeAnthropic([paused, StatusError(400)])),
        gpt: FakeRunner(gpt),
    }
    res = go(tmp_path, rs, qs=QS[:1])
    key = ask_key(CFG, 1, QS[0], claude)
    env = RawStore(tmp_path).get("ask_partial", key)
    assert env["responses"] == [paused] or env["responses"][0]["stop_reason"] == "pause_turn"
    assert env["cost_usd"] > 0 and not RawStore(tmp_path).has("ask", key)
    errs = [e for e in res.errors if e["model"] == claude]
    assert [e["error"] for e in errs] == ["provider:400"] and errs[0]["cost_usd"] > 0
    lines = spend_lines(tmp_path)
    assert len(lines) == 2 and round(sum(x["spent_usd"] for x in lines), 6) == res.spent_usd


def test_a_bad_key_on_a_continuation_stops_that_model(tmp_path):
    from citewatch.runners.anthropic_runner import AnthropicRunner

    from .helpers import FakeAnthropic, claude_raw

    paused = claude_raw()
    paused["stop_reason"] = "pause_turn"
    claude, gpt = CFG.models
    fake = FakeAnthropic([paused, StatusError(401)] + [StatusError(401)] * 10)
    rs = {claude: AnthropicRunner(claude, client=fake), gpt: FakeRunner(gpt)}
    res = go(tmp_path, rs, per_provider=1)
    assert len(fake.calls) == 2 and res.cancelled == len(QS) - 1


def test_editing_a_question_text_asks_it_again(tmp_path):
    go(tmp_path, runners(), qs=QS[:1])
    edited = [QS[0].model_copy(update={"text": "A different question?"})]
    assert go(tmp_path, runners(), qs=edited).asked == 2  # same id, new text: never the old answer
    assert go(tmp_path, runners(), qs=QS[:1]).cached == 2


def test_a_smoke_sized_run_under_a_tight_cap_asks_everything(tmp_path):
    """N1.2 v2 M2: refusals caused only by in-flight reservations wait instead of skipping."""
    from citewatch.cost import answer_cost

    one = max(
        answer_cost(PRICES[m], tokens_in=20000, tokens_out=500, searches=1) for m in CFG.models
    )
    cap = round(len(QS) * len(CFG.models) * one * 1.05, 6)
    assert cap < 8 * 0.095 * INITIAL_RESERVE_FACTOR  # the first reservations alone would refuse
    res = go(tmp_path, runners(delay=0.02), cap=cap)
    assert res.asked == 12 and not res.stopped_at_cap and res.spent_usd <= cap


def test_the_cap_counts_reservations_held_by_calls_in_flight():
    cap = SpendCap(1.0, initial_reserve=0.4)
    assert cap.reserve() == 0.4 and cap.reserve() == 0.4
    assert cap.reserve() is None  # 0.8 reserved + 0.4 > 1.0 although nothing is spent yet
    stop = threading.Event()
    stop.set()
    assert cap.reserve_wait(stop) is None  # a stop never waits
    cap.settle(0.4, 0.1)
    assert cap.reserve_wait(threading.Event()) == 0.1  # settles make room again


def test_workers_waiting_for_a_slot_start_nothing_after_stop(tmp_path):
    """N1.2 v2 M1: a slow provider piles workers on its slot; a stop must not let them go."""
    starts: list[float] = []

    class Timed(FakeRunner):
        def call(self, q, cfg):
            starts.append(time.monotonic())
            return super().call(q, cfg)

    claude, gpt = CFG.models
    qs = [
        StudyQuestion(id=f"v-{i:03d}", text=f"Q{i}?", intent="fitness", time_sensitive=False)
        for i in range(1, 31)
    ]
    rs = {claude: Timed(claude, delay=0.5), gpt: Timed(gpt, delay=0.0)}
    stop = threading.Event()
    stopped_at: list[float] = []

    def fire():
        stopped_at.append(time.monotonic())
        stop.set()

    timer = threading.Timer(0.15, fire)
    timer.start()
    res = go(tmp_path, rs, qs=qs, per_provider=2, stop=stop)
    timer.cancel()
    late = [s for s in starts if s > stopped_at[0] + 0.15]  # waiters would start at +0.35s
    assert late == [] and res.cancelled > 0
    assert len(spend_lines(tmp_path)) == res.asked == sum(len(r.calls) for r in rs.values())


def test_a_paid_response_without_tokens_is_charged_its_reservation(tmp_path):
    rs = runners(tokens_in=0, tokens_out=0)
    res = go(tmp_path, rs, qs=QS[:1])
    assert {e["error"] for e in res.errors} == {"unpriced"} and res.spent_usd > 0


def test_mixed_reservation_sizes_never_leave_the_cap_waiting_forever():
    """v3 H1: 0.1 + 0.2 - 0.1 - 0.2 is not 0.0 in floats; in-flight calls are counted instead."""
    cap = SpendCap(1.74, initial_reserve=0.1)
    held = [cap.reserve(), cap.reserve()]
    first = held.pop(0)
    assert first is not None
    cap.settle(first, 0.2)  # reservations now 0.2 each
    held += [cap.reserve(), cap.reserve()]
    for r, actual in zip(held, (0.3, 0.17, 0.29), strict=True):
        assert r is not None
        cap.settle(r, actual)
    assert cap.in_flight == 0 and cap.reserved == 0.0
    out: list[float | None] = [0.0]
    cap.spent = 1.70  # a little room, less than one call
    cap.reserve_each = 0.3
    th = threading.Thread(
        target=lambda: out.__setitem__(0, cap.reserve_wait(threading.Event())), daemon=True
    )
    th.start()
    th.join(2)
    assert not th.is_alive()
    assert out[0] == pytest.approx(0.04)  # the last call gets the room left
    cap.settle(0.04, 0.3)
    th = threading.Thread(
        target=lambda: out.__setitem__(0, cap.reserve_wait(threading.Event())), daemon=True
    )
    th.start()
    th.join(2)
    assert not th.is_alive() and out[0] is None  # spent money leaves no room: stop, never wait


@pytest.mark.parametrize("seed", range(6))
def test_runs_with_varying_costs_always_end_at_the_cap(tmp_path, seed):
    import random

    rng = random.Random(seed)
    costs = {q.id: rng.choice([5_000, 21_000, 47_000, 133_000]) for q in QS * 3}

    class Varying(FakeRunner):
        def call(self, q, cfg):
            self.tokens_in = costs[q.id]
            return super().call(q, cfg)

    qs = [
        StudyQuestion(id=f"v-{i:03d}", text=f"Q{i}?", intent="fitness", time_sensitive=False)
        for i in range(1, 19)
    ]
    costs = {q.id: rng.choice([5_000, 21_000, 47_000, 133_000]) for q in qs}
    rs = {m: Varying(m, delay=0.002) for m in CFG.models}
    box: list = []
    th = threading.Thread(target=lambda: box.append(go(tmp_path, rs, qs=qs, cap=1.0)), daemon=True)
    th.start()
    th.join(20)
    assert not th.is_alive(), "the run hung at the cap"
    assert box[0].stopped_at_cap and box[0].asked + box[0].skipped_for_cap == 36


def test_a_broken_run_log_never_loses_a_paid_response(tmp_path, monkeypatch):
    """v3 L2: run.log unwritable and an unpriceable response: spend and the answer still land."""

    def broken(self, *a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(Ledger, "event", broken)

    class Odd(FakeRunner):
        def usage(self, responses):
            raise ValueError("unexpected usage shape")

    rs = {m: Odd(m) for m in CFG.models}
    res = go(tmp_path, rs, qs=QS[:2], cap=5.0)
    assert len(spend_lines(tmp_path)) == 4 and res.asked == 4
    assert {e["error"] for e in res.errors} == {"unpriced", "run-log"}
    assert all(
        RawStore(tmp_path).has("ask", ask_key(CFG, 1, q, m)) for q in QS[:2] for m in CFG.models
    )


def test_moving_the_city_asks_again():
    moved = CFG.model_copy(
        update={"user_location": CFG.user_location.model_copy(update={"city": "Leeds"})}
    )
    assert answer_config_hash(moved) != answer_config_hash(CFG)


def _bounded(fn, timeout=20):
    """Run fn in a daemon thread; fail (not hang) if it does not end."""
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    assert not th.is_alive(), "the run hung"
    return box


def test_a_second_ctrl_c_never_abandons_a_call_in_flight(tmp_path, monkeypatch):
    """N1.2 v4 M1: Ctrl-C, then Ctrl-C again while in-flight calls finish."""
    import concurrent.futures

    import citewatch.runners.schedule as sch

    real_wait = real_drain = concurrent.futures.wait
    n = {"wait": 0, "drain": 0}

    def first_interrupt(*a, **k):
        n["wait"] += 1
        if n["wait"] == 2:
            raise KeyboardInterrupt
        return real_wait(*a, **k)

    def second_interrupt(*a, **k):
        n["drain"] += 1
        if n["drain"] == 1:
            raise KeyboardInterrupt
        return real_drain(*a, **k)

    monkeypatch.setattr(sch, "wait", first_interrupt)
    monkeypatch.setattr(sch, "_drain_wait", second_interrupt)
    qs = [
        StudyQuestion(id=f"v-{i:03d}", text=f"Q{i}?", intent="fitness", time_sensitive=False)
        for i in range(1, 31)
    ]
    rs = runners(delay=0.3)
    res = go(tmp_path, rs, qs=qs, per_provider=2)
    made = sum(len(r.calls) for r in rs.values())
    assert res.interrupted and n["drain"] >= 2 and 0 < made < 60
    assert len(spend_lines(tmp_path)) == made == res.asked  # every started call recorded


def test_failures_under_a_cap_never_leak_a_reservation(tmp_path):
    """N1.2 v4 M2: transport and provider errors settle their reservations under a cap."""
    fail = {
        "v-002": TransportError("gone"),
        "v-003": StatusError(400),
        "v-005": TransportError("gone"),
    }
    box = _bounded(lambda: go(tmp_path, runners(fail=fail), cap=0.6))
    res = box["value"]
    assert res.stopped_at_cap or res.asked + len(res.errors) == 12
    assert {e["error"] for e in res.errors} >= {"transport", "provider:400"}


def test_a_runner_bug_after_a_paid_call_is_recorded_and_ends_the_run(tmp_path):
    class Garbage(FakeRunner):
        def call(self, q, cfg):  # type: ignore[override]
            super().call(q, cfg)
            return None  # a bug: paid, but nothing usable came back

    rs = {m: Garbage(m) for m in CFG.models}
    box = _bounded(lambda: go(tmp_path, rs, qs=QS[:2], cap=0.6))
    assert isinstance(box.get("error"), AttributeError)
    made = sum(len(r.calls) for r in rs.values())
    assert made >= 1 and len(spend_lines(tmp_path)) == made  # every paid call has its line


def test_a_missing_runner_raises_instead_of_hanging(tmp_path):
    rs = {CFG.models[0]: FakeRunner(CFG.models[0])}
    box = _bounded(lambda: go(tmp_path, rs, cap=0.6))
    assert isinstance(box.get("error"), KeyError)


def test_the_search_limit_is_part_of_the_answer_key():
    more = CFG.model_copy(update={"max_searches": CFG.max_searches + 1})
    assert answer_config_hash(more) != answer_config_hash(CFG)


def test_an_interrupt_under_a_tight_cap_is_not_reported_as_the_cap(tmp_path):
    stop = threading.Event()
    timer = threading.Timer(0.05, stop.set)
    timer.start()
    qs = [
        StudyQuestion(id=f"v-{i:03d}", text=f"Q{i}?", intent="fitness", time_sensitive=False)
        for i in range(1, 21)
    ]
    res = go(tmp_path, runners(delay=0.1), qs=qs, cap=0.3, stop=stop)
    timer.cancel()
    assert not res.stopped_at_cap and res.skipped_for_cap == 0 and res.cancelled > 0


def test_per_provider_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="per_provider"):
        go(tmp_path, runners(), per_provider=0)


def test_a_cheap_first_call_never_shrinks_reservations_below_the_plan():
    cap = SpendCap(10.0, initial_reserve=0.4, floor=0.1)
    r = cap.reserve()
    assert r is not None
    cap.settle(r, 0.01)  # a quick refusal
    assert cap.reserve_each == 0.1
