"""Write a study's `cost_model.yaml` from the answers its smoke run stored (SMK-02).

uv run python scripts/measure_cost.py studies/uk-health --run 0
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import yaml

from citewatch.cost import measure


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("study", type=Path)
    ap.add_argument("--run", type=int, default=0)
    args = ap.parse_args()
    recs = []
    for f in sorted((args.study / "data" / "raw" / "ask").glob("*/*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("run") == args.run:
            recs.append(d)
    out = measure(recs)
    out = {"source": f"run {args.run}: {len(recs)} stored answers", **out}
    text = "# Measured per-answer usage from the smoke run; `citewatch ask` estimates from it.\n"
    text += yaml.safe_dump(out, sort_keys=True)
    (args.study / "cost_model.yaml").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
