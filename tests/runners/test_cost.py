import datetime as dt
import math

import pytest

from citewatch.cost import (
    Price,
    PriceError,
    answer_cost,
    estimate_run,
    load_prices,
    record_spend,
)
from citewatch.ledger import LedgerError

from .helpers import envelope


def test_recorded_costs_match_a_hand_calculation():
    prices = load_prices()
    for model in ("claude-sonnet-5-5", "gpt-6.1-sol"):
        env = envelope(model, "v-901")
        a, p = env["answer"], prices[model]
        hand = (
            (a["tokens_in"] - a["cached_in"]) * p.input
            + a["cached_in"] * p.cached_input
            + a["tokens_out"] * p.output
        ) / 1e6 + a["searches"] * p.search_per_1k / 1000
        assert math.isclose(env["cost_usd"], hand, rel_tol=1e-12)


def test_long_context_price_applies_above_the_threshold():
    p = load_prices()["gpt-6.1-sol"]
    short = answer_cost(p, tokens_in=272_000, tokens_out=0)
    long = answer_cost(p, tokens_in=272_001, tokens_out=0)
    assert math.isclose(short, 272_000 * 2 / 1e6) and math.isclose(long, 272_001 * 4 / 1e6)


def test_estimate_matches_the_tech_spec_plan():
    est = estimate_run(100, ["claude-sonnet-5-5", "gpt-6.1-sol"], load_prices())
    assert est["total_usd"] == pytest.approx(19.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tokens_in": -1, "tokens_out": 0},
        {"tokens_in": 1, "tokens_out": True},
        {"tokens_in": 1, "tokens_out": 0, "cached_in": 2},
        {"tokens_in": 1.5, "tokens_out": 0},
    ],
)
def test_bad_token_counts(kwargs):
    with pytest.raises(PriceError):
        answer_cost(load_prices()["claude-sonnet-5-5"], **kwargs)


def test_bad_prices_are_errors(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "m:\n  input: .nan\n  output: 1\n  cached_input: 0\n  search_per_1k: 10\n"
        "  checked_on: 2026-11-15\n",
        encoding="utf-8",
    )
    with pytest.raises(PriceError):
        load_prices(p)
    p.write_text("m:\n  input: 1\n", encoding="utf-8")
    with pytest.raises(PriceError):
        load_prices(p)
    with pytest.raises(PriceError, match="no price"):
        estimate_run(1, ["claude-unknown-1"], load_prices())


def test_spend_ledger_appends_one_line_per_spend(tmp_path):
    led = tmp_path / "spend.jsonl"
    record_spend(led, kind="ask", run_id="r1", spent_usd=0.25)
    record_spend(led, kind="ask", run_id="r2", spent_usd=0.5, note="x")
    lines = led.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and '"spent_usd": 0.5' in lines[1]
    with pytest.raises(LedgerError):
        record_spend(led, kind="ask", run_id="r3", spent_usd=-1)


def test_price_dataclass_is_frozen():
    p = Price("m", 1, 1, 0, 10, dt.date(2026, 11, 15))
    with pytest.raises(AttributeError):
        p.input = 2  # type: ignore[misc]


def test_cached_tokens_are_priced_once_at_the_cached_rate():
    p = load_prices()["claude-sonnet-5-5"]
    cost = answer_cost(p, tokens_in=10_000, tokens_out=0, cached_in=4_000)
    assert math.isclose(cost, (6_000 * p.input + 4_000 * p.cached_input) / 1e6)
    assert cost < answer_cost(p, tokens_in=10_000, tokens_out=0)


def test_spend_lines_never_tear_when_threads_append_at_once(tmp_path, monkeypatch):
    """Simulates a non-atomic append (what Windows does across handles): each write is split
    into pieces with a pause between them. Without the per-file lock, lines interleave."""
    import io
    import json
    import threading
    import time
    from pathlib import Path

    real_open = Path.open

    class Slow(io.TextIOWrapper):
        pass

    def slow_open(self, mode="r", *a, **k):
        fh = real_open(self, mode, *a, **k)
        if "a" not in mode:
            return fh
        write = fh.write

        def chunked(s):
            for i in range(0, len(s), 7):
                write(s[i : i + 7])
                fh.flush()
                time.sleep(0.0002)
            return len(s)

        fh.write = chunked  # type: ignore[method-assign]
        return fh

    monkeypatch.setattr(Path, "open", slow_open)
    led = tmp_path / "spend.jsonl"

    def worker(i):
        for j in range(15):
            record_spend(led, kind="answer", run_id=f"r{i}", spent_usd=0.01, note=f"{i}-{j}" * 5)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = led.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 120
    assert all(json.loads(x)["spent_usd"] == 0.01 for x in lines)


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ("- a\n- b\n", "must map"),
        ("m: [1, 2]\n", "must be a mapping"),
        (
            "m:\n  input: -1\n  output: 1\n  cached_input: 0\n  search_per_1k: 1\n"
            "  checked_on: 2026-11-15\n",
            "negative",
        ),
        (
            "m:\n  input: 1\n  output: 1\n  cached_input: 0\n  search_per_1k: 1\n"
            "  checked_on: 2099-01-01\n",
            "future",
        ),
        ("m: {input: 1\n", "not valid YAML"),
    ],
)
def test_malformed_prices_are_price_errors(tmp_path, body, needle):
    p = tmp_path / "prices.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(PriceError, match=needle):
        load_prices(p)


def test_a_datetime_checked_on_is_read_as_its_date(tmp_path):
    p = tmp_path / "prices.yaml"
    p.write_text(
        "m:\n  input: 1\n  output: 1\n  cached_input: 0\n  search_per_1k: 1\n"
        "  checked_on: 2026-11-15 10:00:00\n",
        encoding="utf-8",
    )
    assert load_prices(p)["m"].checked_on == dt.date(2026, 11, 15)
