"""RUN-03: the spend ledger, the raw records' costs and a recomputation from provider usage agree.

    uv run python scripts/reconcile_spend.py studies/uk-health --runs 1 2

Exits 1 if any two disagree by more than 10%, or the ledger and raw records differ in count.
The provider's own bill is checked by hand against its console (usage is per day, not per call).
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

from citewatch.cost import answer_cost, load_prices, price_for
from citewatch.schemas import load_study_config

TOLERANCE = 0.10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study", type=Path)
    ap.add_argument("--runs", type=int, nargs="+", default=[1, 2])
    a = ap.parse_args()
    cfg = load_study_config(a.study / "study.yaml")
    prices = load_prices()
    bad = False
    for run in a.runs:
        raw = []
        for f in sorted((a.study / "data" / "raw" / "ask").glob("*/*.json.gz")):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("run") == run:
                raw.append(d)
        ledger = [
            float(r["spent_usd"])
            for line in (a.study / "data" / "spend-ledger.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line and (r := json.loads(line)).get("run_id") == f"{cfg.name}:run-{run}"
        ]
        stored = math.fsum(d["cost_usd"] for d in raw)
        recomputed = math.fsum(
            answer_cost(
                price_for(d["model"], prices),
                tokens_in=d["usage"]["tokens_in"],
                tokens_out=d["usage"]["tokens_out"],
                cached_in=d["usage"].get("cached_in", 0),
                searches=d["usage"]["searches"],
            )
            for d in raw
            if d.get("usage")
        )
        figures = [math.fsum(ledger), stored, recomputed]
        spread = (max(figures) - min(figures)) / max(max(figures), 1e-9)
        ok = bool(raw) and len(ledger) == len(raw) and spread <= TOLERANCE  # nothing is not OK
        bad |= not ok
        print(
            f"run {run}: {len(raw)} raw, {len(ledger)} ledger lines; ledger ${figures[0]:.4f}, "
            f"raw ${stored:.4f}, recomputed ${recomputed:.4f}; spread {spread:.2%} "
            + ("OK" if ok else "MISMATCH")
        )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
