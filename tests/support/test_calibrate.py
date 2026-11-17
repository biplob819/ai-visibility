"""OWNER D-65: judge calibration against the owner's labels, using EvalKit's statistics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citewatch.schemas import SupportVerdict, load_study_config
from citewatch.support.calibrate import calibrate
from citewatch.support.report import load_hand_labels

STUDY = Path(__file__).resolve().parents[2] / "studies" / "uk-health"


def _v(ref: str, judge: str, ok: bool) -> SupportVerdict:
    return SupportVerdict(
        citation_ref=ref, judge=judge, verdict="supported" if ok else "unsupported"
    )


def test_confusion_kappa_and_strictness() -> None:
    refs = [f"1:v-{i:03d}:claude-sonnet-5-5:1" for i in range(8)]
    hand = {r: ("supported" if i < 4 else "unsupported") for i, r in enumerate(refs)}
    hand["1:v-009:claude-sonnet-5-5:1"] = "cant_tell"
    verdicts = [_v(r, "j", i in (0, 1, 2, 4)) for i, r in enumerate(refs)]
    verdicts.append(_v("1:v-009:claude-sonnet-5-5:1", "j", True))
    (row,) = calibrate(verdicts, hand, seed=1)
    assert row["confusion"] == {"tp": 3, "fn": 1, "fp": 1, "tn": 3}
    assert row["n"] == 8 and row["owner_cant_tell"] == 1
    assert row["agreement"] == pytest.approx(0.75)
    assert row["kappa"] == pytest.approx(0.5)
    assert row["strictness"] == pytest.approx(0.25)
    lo, hi = row["kappa_interval"]
    assert lo <= 0.5 <= hi


def test_constant_owner_labels_are_flagged() -> None:
    refs = [f"1:v-{i:03d}:claude-sonnet-5-5:1" for i in range(4)]
    hand = dict.fromkeys(refs, "supported")
    verdicts = [_v(r, "j", i < 2) for i, r in enumerate(refs)]
    (row,) = calibrate(verdicts, hand, seed=1)
    assert row["owner_constant"] is True
    assert row["kappa"] == 0.0
    assert row["strictness"] == pytest.approx(0.5)
    assert row["leniency"] is None


def test_calibration_is_reproduced_from_the_committed_data():
    cfg = load_study_config(STUDY / "study.yaml")
    verdicts = [
        SupportVerdict.model_validate(r)
        for r in [
            json.loads(x)
            for x in (STUDY / "data" / "support_verdicts.jsonl").read_text("utf-8").splitlines()
            if x.strip()
        ]
    ]
    rows = calibrate(verdicts, load_hand_labels(STUDY), cfg.seeds["support_sample"])
    stored = json.loads((STUDY / "results" / "calibration.json").read_text("utf-8"))
    assert json.loads(json.dumps(rows)) == stored["judges"]
