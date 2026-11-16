"""SUP-04..06: support rates, judge–hand agreement, the answer-to-fetch gap, and finalise.

- Support rate per cited model, for each AI judge and for the owner's hand labels ("hand"),
  with Wilson intervals. "Can't tell" hand labels and AI-unjudged citations leave that rate's
  denominator and are counted.
- Agreement per judge with the hand labels: the share of citations where both gave a verdict and
  they match, and Cohen's kappa with a seeded bootstrap interval over citations.
- The gap in days between each citation's answer and the fetch its kept text came from.
- `finalise` deletes the body cache and EvalKit store and checks both are gone (NFR6).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from citewatch.metrics.stats import make_interval, percentiles, wilson
from citewatch.schemas import SupportRow, SupportVerdict

HAND = "hand"
LABELS_FILE = "support_labels.jsonl"
KEY_FILE = "support_label_key.jsonl"


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def model_of(citation_ref: str) -> str:
    return citation_ref.split(":")[2]


def kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """Cohen's kappa for two binary raters; None when undefined (chance agreement is 1)."""
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe >= 1 else (po - pe) / (1 - pe)


def kappa_interval(a: Sequence[bool], b: Sequence[bool], seed: int, resamples: int = 10_000) -> Any:
    point = kappa(a, b)
    if point is None:
        return None
    rng = np.random.default_rng(seed)
    x, y = np.array(a, dtype=float), np.array(b, dtype=float)
    idx = rng.integers(0, len(x), size=(resamples, len(x)))
    xs, ys = x[idx], y[idx]
    po = (xs == ys).mean(axis=1)
    pa, pb = xs.mean(axis=1), ys.mean(axis=1)
    pe = pa * pb + (1 - pa) * (1 - pb)
    with np.errstate(divide="ignore", invalid="ignore"):
        vals = np.where(pe < 1, (po - pe) / (1 - pe), np.nan)
    lo, hi = percentiles(vals[:, None])
    return make_interval(point, float(lo[0]), float(hi[0]), n=len(a))


def support_rows(
    verdicts: Sequence[SupportVerdict],
    hand: Mapping[str, str],
    seed: int,
) -> list[SupportRow]:
    """`hand` maps citation_ref -> "supported" | "unsupported" | "cant_tell"."""
    rows: list[SupportRow] = []
    judges = sorted({v.judge for v in verdicts})
    models = sorted({model_of(v.citation_ref) for v in verdicts} | {model_of(r) for r in hand})
    by = {(v.judge, v.citation_ref): v.verdict == "supported" for v in verdicts}
    for model in models:
        for judge in [*judges, HAND]:
            if judge == HAND:
                refs = [r for r, lab in hand.items() if model_of(r) == model and lab != "cant_tell"]
                got = [hand[r] == "supported" for r in refs]
                rows.append(
                    SupportRow(model=model, judge=HAND, support_rate=wilson(sum(got), len(got)))
                )
                continue
            refs = sorted(r for (j, r) in by if j == judge and model_of(r) == model)
            got = [by[(judge, r)] for r in refs]
            both = [r for r in refs if hand.get(r) in ("supported", "unsupported")]
            a = [by[(judge, r)] for r in both]
            b = [hand[r] == "supported" for r in both]
            rows.append(
                SupportRow(
                    model=model,
                    judge=judge,
                    support_rate=wilson(sum(got), len(got)),
                    hand_agreement=(sum(x == y for x, y in zip(a, b, strict=True)) / len(a))
                    if a
                    else None,
                    kappa=kappa_interval(a, b, seed) if a else None,
                )
            )
    return rows


def load_hand_labels(base: Path) -> dict[str, str]:
    """citation_ref -> label, from the imported labels and the page-id key."""
    key = {r["id"]: r["citation_ref"] for r in _rows(base / "data" / KEY_FILE)}
    out = {}
    for r in _rows(base / "data" / LABELS_FILE):
        ref = r.get("citation_ref") or key.get(r.get("id", ""))
        if ref and r.get("label") in ("supported", "unsupported", "cant_tell"):
            out[ref] = r["label"]
    return out


def gaps(base: Path) -> list[dict[str, Any]]:
    """SUP-06: days from each sampled citation's answer to the fetch its kept text came from."""
    data = base / "data"
    answered = {
        (a["run"], a["question_id"], a["model"]): a["answered_at"]
        for a in _rows(data / "answers.jsonl")
    }
    fetched = {
        r["url"]: r["fetched_at"]
        for r in _rows(data / "support_text_fetches.jsonl")
        if r.get("fetched_at")
    }
    cites = {
        f"{c['run']}:{c['question_id']}:{c['model']}:{c['ordinal']}": c
        for c in _rows(data / "citations.jsonl")
    }
    out = []
    for r in _rows(data / KEY_FILE):
        c = cites.get(r["citation_ref"])
        if c is None:
            continue
        a = answered.get((c["run"], c["question_id"], c["model"]))
        f = fetched.get(c["url"])
        if a and f:
            t0 = dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
            t1 = dt.datetime.fromisoformat(f.replace("Z", "+00:00"))
            out.append(
                {
                    "citation_ref": r["citation_ref"],
                    "gap_days": round((t1 - t0).total_seconds() / 86400, 3),
                }
            )
    return out


def finalise(cache_dir: Path) -> list[str]:
    """Delete the body cache (page text and the EvalKit store inside it); return problems."""
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    return [f"{cache_dir} still exists after finalise"] if cache_dir.exists() else []
