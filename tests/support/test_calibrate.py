"""OWNER D-65: judge calibration against the owner's labels, using EvalKit's statistics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citewatch.schemas import SupportVerdict, load_study_config
from citewatch.support.report import load_hand_labels

STUDY = Path(__file__).resolve().parents[2] / "studies" / "uk-health"


@pytest.fixture
def calibrate():
    """citewatch's calibration (needs the `support` extra, as test_judge's fixture does)."""
    pytest.importorskip("evalkit")
    from citewatch.support.calibrate import calibrate

    return calibrate


def _v(ref: str, judge: str, ok: bool) -> SupportVerdict:
    return SupportVerdict(
        citation_ref=ref, judge=judge, verdict="supported" if ok else "unsupported"
    )


def test_confusion_kappa_and_strictness(calibrate) -> None:
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


def test_constant_owner_labels_are_flagged(calibrate) -> None:
    refs = [f"1:v-{i:03d}:claude-sonnet-5-5:1" for i in range(4)]
    hand = dict.fromkeys(refs, "supported")
    verdicts = [_v(r, "j", i < 2) for i, r in enumerate(refs)]
    (row,) = calibrate(verdicts, hand, seed=1)
    assert row["owner_constant"] is True
    assert row["kappa"] is None and row["kappa_interval"] is None
    assert row["strictness"] == pytest.approx(0.5)
    assert row["leniency"] is None


def test_calibration_is_reproduced_from_the_committed_data(calibrate):
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


def test_the_evalkit_calibration_symbols_citewatch_imports_keep_their_shape(calibrate):
    """Contract (M3.2 pass 1, M3): the names calibrate.py imports, until EvalKit 0.3 (D-66)."""
    import dataclasses
    import inspect

    from evalkit.pipeline.calibrate import _Pair, cluster_kappa, kappa_from

    assert [f.name for f in dataclasses.fields(_Pair)] == ["answer", "human", "judge"]
    assert list(inspect.signature(kappa_from).parameters) == ["tp", "fn", "fp", "tn"]
    params = inspect.signature(cluster_kappa).parameters
    assert next(iter(params)) == "pairs" and "seed" in params
    assert cluster_kappa([_Pair("a", True, True), _Pair("b", False, False)], seed=1).point == 1.0


def test_score_runs_without_the_support_extra(tmp_path, monkeypatch):
    """Pass 1 H1: a default install (no EvalKit) still scores a study that has labels."""
    import shutil
    import sys

    from citewatch.cli import main

    study = tmp_path / "uk-health"
    shutil.copytree(STUDY, study, ignore=shutil.ignore_patterns("raw", "results"))
    shutil.copy(
        STUDY.parent.parent / "docs" / "preregistration.md", tmp_path / "preregistration.md"
    )
    for name in [
        m
        for m in sys.modules
        if m == "evalkit" or m.startswith(("evalkit.", "citewatch.support.calibrate"))
    ]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "evalkit", None)
    assert main(["score", "--study", str(study)]) == 0
    assert (study / "results" / "summary.json").is_file()
    assert not (study / "results" / "calibration.json").exists()
