"""Prices, per-answer cost, the pre-run estimate and the spend ledger (Tech Spec §10, ASK-06).

Every money value is checked finite and non-negative before it is added, compared with a cap
or written down (L-7). Prices come only from prices.yaml.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import yaml

from citewatch.ledger import check_money

# Planning assumptions per answer (Tech Spec §10), replaced by the smoke run's measured averages.
ASSUMPTIONS = {"tokens_in": 25_000, "tokens_out": 1_500, "searches": 3}


class PriceError(ValueError):
    """A model has no price, or a price is invalid."""


@dataclass(frozen=True)
class Price:
    model: str
    input: float
    output: float
    cached_input: float
    search_per_1k: float
    checked_on: dt.date
    long_threshold: int | None = None
    long_input: float | None = None
    long_output: float | None = None


def load_prices(path: Path | None = None) -> dict[str, Price]:
    text = (
        path.read_text(encoding="utf-8")
        if path
        else files("citewatch").joinpath("prices.yaml").read_text(encoding="utf-8")
    )
    from citewatch.schemas.config import ConfigError, _UniqueKeyLoader

    try:
        raw = yaml.load(text, Loader=_UniqueKeyLoader) or {}
    except ConfigError as exc:  # a duplicated model silently kept the last entry (v3 L3)
        raise PriceError(f"prices.yaml: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PriceError(f"prices.yaml is not valid YAML ({exc})") from exc
    if not isinstance(raw, dict):
        raise PriceError("prices.yaml must map each model to its prices")
    prices = {}
    for model, p in raw.items():
        try:
            if not isinstance(model, str) or not model:
                raise PriceError(f"prices.yaml: model names must be text, got {model!r}")
            if not isinstance(p, dict):
                raise PriceError(f"prices.yaml: {model} must be a mapping of prices")
            p = cast(dict[str, Any], p)
            fields = {k: p[k] for k in ("input", "output", "cached_input", "search_per_1k")}
            for k, v in fields.items():
                try:
                    check_money(v, f"{model}.{k}")
                except ValueError as exc:
                    raise PriceError(f"prices.yaml: {exc}") from exc
            checked = p["checked_on"]
            if isinstance(checked, dt.datetime):
                checked = checked.date()
            if not isinstance(checked, dt.date):
                raise PriceError(f"{model}.checked_on must be a date")
            if checked > dt.date.today() + dt.timedelta(days=1):
                raise PriceError(f"{model}.checked_on {checked} is in the future")
            threshold, long_in, long_out = (
                p.get(k) for k in ("long_threshold", "long_input", "long_output")
            )
            if threshold is not None:
                if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
                    raise PriceError(
                        f"prices.yaml: {model}.long_threshold must be a positive whole number of "
                        f"tokens, got {threshold!r} (write 150000, not 1.5e5)"
                    )
                for k, v in (("long_input", long_in), ("long_output", long_out)):
                    try:
                        if v is None:
                            raise ValueError(f"{model}.{k} is required with long_threshold")
                        if check_money(v, f"{model}.{k}") == 0:
                            raise ValueError(f"{model}.{k} cannot be 0")
                    except ValueError as exc:
                        raise PriceError(f"prices.yaml: {exc}") from exc
            elif long_in is not None or long_out is not None:
                raise PriceError(f"prices.yaml: {model} has long prices but no long_threshold")
            prices[model] = Price(
                model=model,
                input=float(fields["input"]),
                output=float(fields["output"]),
                cached_input=float(fields["cached_input"]),
                search_per_1k=float(fields["search_per_1k"]),
                checked_on=checked,
                long_threshold=threshold,
                long_input=None if long_in is None else float(long_in),
                long_output=None if long_out is None else float(long_out),
            )
        except (KeyError, TypeError) as exc:
            raise PriceError(f"prices.yaml: {model} is missing or has a bad field ({exc})") from exc
    return prices


def price_for(model: str, prices: Mapping[str, Price]) -> Price:
    if model not in prices:
        raise PriceError(f"no price for model {model!r} in prices.yaml; add one before running")
    return prices[model]


def answer_cost(
    price: Price, *, tokens_in: int, tokens_out: int, cached_in: int = 0, searches: int = 0
) -> float:
    """USD for one answer: uncached input, cached input, output (reasoning included) and the
    per-search fee. Search-result tokens are part of tokens_in on both providers (D-31)."""
    for name, v in (
        ("tokens_in", tokens_in),
        ("tokens_out", tokens_out),
        ("cached_in", cached_in),
        ("searches", searches),
    ):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise PriceError(f"{name} must be a non-negative integer, got {v!r}")
    if cached_in > tokens_in:
        raise PriceError("cached_in cannot exceed tokens_in")
    p_in, p_out = price.input, price.output
    if price.long_threshold is not None and tokens_in > price.long_threshold:
        p_in, p_out = price.long_input or p_in, price.long_output or p_out
    cost = (
        (tokens_in - cached_in) * p_in / 1e6
        + cached_in * price.cached_input / 1e6
        + tokens_out * p_out / 1e6
        + searches * price.search_per_1k / 1000
    )
    return check_money(cost)


def estimate_run(
    n_questions: int | Mapping[str, int],
    models: Iterable[str],
    prices: Mapping[str, Price],
    assumptions: Mapping[str, int] = ASSUMPTIONS,
) -> dict[str, Any]:
    """Calls and estimated USD per model and in total, before any call is made. `n_questions`
    may be a count per model (a resumed run counts only the calls not yet stored)."""
    per_model = {}
    for m in models:
        n = n_questions.get(m, 0) if isinstance(n_questions, Mapping) else n_questions
        one = answer_cost(
            price_for(m, prices),
            tokens_in=assumptions["tokens_in"],
            tokens_out=assumptions["tokens_out"],
            searches=assumptions["searches"],
        )
        per_model[m] = {"calls": n, "usd": check_money(round(one * n, 6))}
    total = check_money(math.fsum(v["usd"] for v in per_model.values()))
    return {"per_model": per_model, "total_usd": round(total, 6), "assumptions": dict(assumptions)}


def price_age_days(prices: Mapping[str, Price], today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return max((today - p.checked_on).days for p in prices.values()) if prices else 0


def record_spend(
    ledger_path: Path, *, kind: str, run_id: str, spent_usd: float, note: str = ""
) -> dict[str, Any]:
    """Append one line to the spend ledger (OWNER D-19: every real dollar is written down)."""
    row = {
        "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "kind": kind,
        "run_id": run_id,
        "spent_usd": round(check_money(spent_usd, "spent_usd"), 6),
        "note": note,
    }
    line = json.dumps(row, sort_keys=True) + "\n"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(ledger_path), ledger_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)  # one locked write per line: appends from threads never tear (Windows)
    return row


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())
