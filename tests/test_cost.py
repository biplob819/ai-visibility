import datetime as dt

import pytest

# --- A2.4: measured cost model (SMK-02) --------------------------------------------------------


def _rec(model, tin, tout, s, cost, error=None):
    return {
        "model": model,
        "usage": {"tokens_in": tin, "tokens_out": tout, "searches": s, "cached_in": 0},
        "cost_usd": cost,
        "error": error,
    }


def test_measure_takes_means_with_headroom_rounded_up():
    from citewatch.cost import measure

    out = measure(
        [
            _rec("m", 1000, 100, 1, 0.01),
            _rec("m", 2000, 300, 2, 0.03),
            _rec("m", 9, 9, 9, 9, "transport"),
        ]
    )
    row = out["models"]["m"]
    assert row == {
        "tokens_in": 1875,
        "tokens_out": 250,
        "searches": 2,
        "answers": 2,
        "mean_cost_usd": 0.02,
    }


def test_load_measured_rejects_bad_values(tmp_path):
    from citewatch.cost import PriceError, load_measured

    p = tmp_path / "cost_model.yaml"
    assert load_measured(p) is None
    p.write_text("models:\n  m: {tokens_in: 10, tokens_out: 5, searches: 1}\n", encoding="utf-8")
    assert load_measured(p) == {"m": {"tokens_in": 10, "tokens_out": 5, "searches": 1}}
    for bad in ("models: 3\n", "models:\n  m: {tokens_in: -1, tokens_out: 5, searches: 1}\n",
                "models:\n  m: {tokens_in: 1.5, tokens_out: 5, searches: 1}\n",
                "models:\n  m: {tokens_in: true, tokens_out: 5, searches: 1}\n"):  # fmt: skip
        p.write_text(bad, encoding="utf-8")
        with pytest.raises(PriceError):
            load_measured(p)


def test_the_estimate_uses_measured_usage_per_model():
    from citewatch.cost import Price, estimate_run

    pr = {
        m: Price(
            model=m,
            input=2.0,
            output=10.0,
            cached_input=0.1,
            search_per_1k=10.0,
            checked_on=dt.date(2026, 11, 15),
        )
        for m in ("a", "b")
    }
    measured = {"a": {"tokens_in": 10_000, "tokens_out": 500, "searches": 1}}
    est = estimate_run(100, ["a", "b"], pr, measured=measured)
    assert est["per_model"]["a"]["usd"] == pytest.approx(100 * (0.02 + 0.005 + 0.01))
    assert est["per_model"]["b"]["usd"] == pytest.approx(100 * (0.05 + 0.015 + 0.03))  # defaults
    assert est["measured"] is True


def test_the_uk_health_cost_model_keeps_two_runs_inside_the_approved_budget():
    """OWNER D-48 approved about $38 for both study runs; OWNER D-19 asks above $25 a run."""
    from pathlib import Path

    from citewatch.cost import estimate_run, load_measured, load_prices
    from citewatch.schemas import load_study_config

    study = Path(__file__).resolve().parent.parent / "studies" / "uk-health"
    cfg = load_study_config(study / "study.yaml")
    est = estimate_run(
        100, cfg.models, load_prices(), measured=load_measured(study / "cost_model.yaml")
    )
    assert est["measured"] and est["total_usd"] < 19
