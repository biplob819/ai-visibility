"""Judge calibration against the owner's support labels, with EvalKit's statistics (OWNER D-65).

EvalKit's own calibration flow (`evalkit.pipeline.calibrate`) labels individual claims with a
tuning and a held-out split. The owner's labels here are one per citation, so citewatch reuses
EvalKit's agreement statistics rather than its labelling flow: the confusion counts, Cohen's
kappa as EvalKit defines it (`kappa_from`), and EvalKit's `cluster_kappa`, whose bootstrap
resamples answers rather than citations, since citations in one answer share a writer.

For each judge, over citations where both the judge and the owner gave a verdict ("can't tell"
and unjudged citations are left out and counted):
- tp / fn / fp / tn with the owner as reference ("supported" is positive);
- agreement, kappa with its interval, and the judge's strictness (the share of citations the
  owner called supported that the judge did not), which is what the support rate's gap
  between judge and owner comes from.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evalkit.pipeline.calibrate import (  # pinned 2181921; `_Pair` until EvalKit 0.3 (D-66)
    _Pair,
    cluster_kappa,
    kappa_from,
)

from citewatch.schemas import SupportVerdict

CALIBRATION_FILE = "calibration.json"


def _answer(citation_ref: str) -> str:
    return citation_ref.rsplit(":", 1)[0]  # "run:question:model:ordinal" -> the answer


def calibrate(
    verdicts: Sequence[SupportVerdict], hand: Mapping[str, str], seed: int
) -> list[dict[str, Any]]:
    rows = []
    for judge in sorted({v.judge for v in verdicts}):
        mine = {v.citation_ref: v.verdict == "supported" for v in verdicts if v.judge == judge}
        both = sorted(r for r in mine if hand.get(r) in ("supported", "unsupported"))
        pairs = [
            _Pair(answer=_answer(r), human=hand[r] == "supported", judge=mine[r]) for r in both
        ]
        tp = sum(p.human and p.judge for p in pairs)
        fn = sum(p.human and not p.judge for p in pairs)
        fp = sum(not p.human and p.judge for p in pairs)
        tn = sum(not p.human and not p.judge for p in pairs)
        constant = len({p.human for p in pairs}) == 1
        # kappa is 0 by construction when the owner's labels are all one value: not reported
        interval = cluster_kappa(pairs, seed=seed) if pairs and not constant else None
        rows.append(
            {
                "judge": judge,
                "n": len(pairs),
                "answers": len({p.answer for p in pairs}),
                "owner_cant_tell": sum(hand.get(r) == "cant_tell" for r in mine),
                "owner_unlabelled": sum(r not in hand for r in mine),
                "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
                "agreement": (tp + tn) / len(pairs) if pairs else None,
                "kappa": kappa_from(tp, fn, fp, tn) if pairs and not constant else None,
                "kappa_interval": [interval.lo, interval.hi] if interval else None,
                "strictness": fn / (tp + fn) if tp + fn else None,
                "leniency": fp / (fp + tn) if fp + tn else None,
                "owner_constant": constant,
            }
        )
    return rows


def write_calibration(base: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    path = base / "results" / CALIBRATION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": "EvalKit cluster_kappa over citations, clustered by answer (OWNER D-65)",
        "judges": list(rows),
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path
