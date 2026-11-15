import json
import math
import threading

import pytest

from citewatch.ledger import Ledger, LedgerError, check_money


def test_one_json_line_per_event(tmp_path):
    led = Ledger(tmp_path / "runs" / "r1")
    led.event("ask", "a" * 64, cache_hit=False, latency_ms=1200, cost_usd=0.07)
    led.event("ask", "b" * 64, cache_hit=True, latency_ms=0, cost_usd=0, error=None)
    rows = led.rows()
    assert [r["key"][0] for r in rows] == ["a", "b"]
    assert rows[0]["at"].endswith("Z") and rows[1]["cache_hit"] is True


def test_concurrent_producers_never_interleave(tmp_path):
    led = Ledger(tmp_path)

    def produce(i):
        for j in range(50):
            led.event(
                "fetch",
                f"{i:02d}{j:062d}",
                cache_hit=False,
                latency_ms=j,
                cost_usd=0.0,
                note="x" * 500,
            )

    threads = [threading.Thread(target=produce, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = (tmp_path / "run.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 400
    assert all(json.loads(x)["note"] == "x" * 500 for x in lines)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.01, "0.1", True, None])
def test_bad_money_is_an_error(tmp_path, bad):
    with pytest.raises(LedgerError):
        Ledger(tmp_path).event("ask", "k", cache_hit=False, latency_ms=1, cost_usd=bad)
    with pytest.raises(LedgerError):
        check_money(bad)


@pytest.mark.parametrize("bad", [-1, 1.5, True])
def test_bad_latency(tmp_path, bad):
    with pytest.raises(LedgerError):
        Ledger(tmp_path).event("ask", "k", cache_hit=False, latency_ms=bad, cost_usd=0)
