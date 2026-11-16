"""RUN-01, RUN-02, RUN-04: gates G1 and G2 and the run manifest (Tech Spec §13)."""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from citewatch.runs import gate_g1, gate_g2, read_manifest, write_manifest
from citewatch.schemas import load_study_config

ROOT = Path(__file__).resolve().parents[2]
NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.UTC)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    study = r / "studies" / "s"
    study.mkdir(parents=True)
    for f in ("study.yaml", "questions.jsonl"):
        shutil.copy(ROOT / "studies" / "uk-health" / f, study / f)
    (r / "src" / "citewatch" / "runners").mkdir(parents=True)
    (r / "src" / "citewatch" / "runners" / "x.py").write_text("A = 1\n", encoding="utf-8")
    (r / "docs").mkdir()
    (r / "docs" / "preregistration.md").write_text("# frozen\n", encoding="utf-8")
    q = hashlib.sha256((study / "questions.jsonl").read_bytes()).hexdigest()
    p = hashlib.sha256(b"# frozen\n").hexdigest()
    (r / "docs" / "decisions.md").write_text(f"| D-1 | {q[:16]} {p[:16]} |\n", encoding="utf-8")
    git(r, "init", "-q")
    git(r, "-c", "user.email=t@e", "-c", "user.name=t", "add", "-A")
    git(r, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "init")
    return study


def g1(study: Path, **kw):
    cfg = load_study_config(study / "study.yaml")
    args = {
        "estimate_usd": 12.0,
        "measured": True,
        "cap_usd": 25.0,
        "prices_age_days": 1,
        "preregistration": study.parents[1] / "docs" / "preregistration.md",
    }
    args.update(kw)
    return gate_g1(study, cfg, **args)


def test_g1_passes_on_a_frozen_clean_measured_study(repo):
    assert g1(repo) == []


@pytest.mark.parametrize(
    ("kw", "needle"),
    [
        ({"measured": False}, "cost_model.yaml"),
        ({"estimate_usd": 30.0}, "over the cap"),
        ({"prices_age_days": 8}, "8 days ago"),
        ({"preregistration": None}, "preregistration"),
    ],
)
def test_g1_refuses_each_unmet_condition(repo, kw, needle):
    assert any(needle in p for p in g1(repo, **kw))


def test_g1_refuses_unrecorded_hashes_and_a_dirty_tree(repo):
    (repo / "questions.jsonl").write_text('{"id": "v-001"}\n', encoding="utf-8")
    problems = g1(repo)
    assert any("questions sha256" in p and "not recorded" in p for p in problems)
    assert any("uncommitted" in p for p in problems)


def _finish_run1(study: Path, at: dt.datetime) -> None:
    cfg = load_study_config(study / "study.yaml")
    write_manifest(
        study,
        1,
        config_hash="abc",
        questions_sha256=None,
        preregistration_sha256=None,
        started_at=at - dt.timedelta(hours=1),
        finished_at=at,
        answers=200,
    )
    git(study.parents[1], "-c", "user.email=t@e", "-c", "user.name=t", "add", "-A")
    git(study.parents[1], "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "run 1")
    assert cfg


def test_g2_needs_run_1_finished(repo):
    cfg = load_study_config(repo / "study.yaml")
    assert any("run 1" in p for p in gate_g2(repo, cfg, NOW))


def test_g2_waits_two_hours_then_passes(repo):
    cfg = load_study_config(repo / "study.yaml")
    _finish_run1(repo, NOW - dt.timedelta(minutes=30))
    assert any("at least 2 hours" in p for p in gate_g2(repo, cfg, NOW))
    assert gate_g2(repo, cfg, NOW + dt.timedelta(hours=2)) == []


@pytest.mark.parametrize("target", ["runner", "study.yaml"])
def test_g2_refuses_code_or_config_changed_since_run_1(repo, target):
    cfg = load_study_config(repo / "study.yaml")
    _finish_run1(repo, NOW - dt.timedelta(hours=3))
    r = repo.parents[1]
    f = r / "src" / "citewatch" / "runners" / "x.py" if target == "runner" else repo / "study.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    git(r, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qam", "change")
    assert any("changed since run 1" in p for p in gate_g2(repo, cfg, NOW))


def test_a_resumed_run_keeps_its_first_start_and_commit(repo):
    t0 = NOW - dt.timedelta(hours=5)
    kw = {
        "config_hash": "abc",
        "questions_sha256": "q",
        "preregistration_sha256": "p",
        "answers": 1,
    }
    write_manifest(repo, 1, started_at=t0, finished_at=None, **kw)
    first = read_manifest(repo, 1)
    assert first is not None and first["finished_at"] is None and first["git_sha"]
    write_manifest(repo, 1, started_at=NOW, finished_at=NOW, **kw)
    second = read_manifest(repo, 1)
    assert second is not None
    assert second["started_at"] == first["started_at"] and second["git_sha"] == first["git_sha"]
    assert second["finished_at"] == "2026-11-20T12:00:00Z"


def test_the_manifest_keeps_the_commit_the_run_started_from(repo):
    """A commit made while a run is going must not become the run's recorded commit."""
    write_manifest(
        repo, 2, config_hash="c", questions_sha256=None, preregistration_sha256=None,
        started_at=NOW, finished_at=NOW, answers=1, run_sha="a" * 40,
    )  # fmt: skip
    m = read_manifest(repo, 2)
    assert m is not None and m["git_sha"] == "a" * 40
