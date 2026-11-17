"""Draw the held-out date sample once (M3.3, Tech Spec §8.2): pages cited in the study runs,
the study's `hand_sample` seed, tuning-set URLs excluded. Refuses to overwrite a drawn sample.

    uv run python scripts/draw_hand_sample.py studies/uk-health
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from citewatch.handcheck import SAMPLE_FILE, draw_hand_sample, study_pages, tuning_urls, write_once
from citewatch.schemas import load_study_config

ROOT = Path(__file__).resolve().parent.parent


def main(base: Path) -> int:
    cfg = load_study_config(base / "study.yaml")
    rows = draw_hand_sample(
        study_pages(base),
        cfg.seeds["hand_sample"],
        exclude=tuning_urls(ROOT / "tests" / "fixtures" / "dates"),
    )
    out = write_once(base / "data" / SAMPLE_FILE, rows)
    print(f"{len(rows)} pages -> {out}: {dict(Counter(r['stratum'] for r in rows))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "studies/uk-health")))
