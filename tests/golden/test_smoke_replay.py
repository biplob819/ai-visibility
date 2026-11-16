"""SMK-05: replay the smoke run offline and get byte-identical outputs (§11, D-52)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from citewatch.dates import build_page_meta, write_page_meta
from citewatch.extract import run_extract
from citewatch.metrics import build_summary, write_summary
from citewatch.schemas import load_questions, load_study_config

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "golden" / "smoke"


@pytest.fixture
def study(tmp_path: Path) -> Path:
    base = tmp_path / "study"
    shutil.copytree(GOLDEN, base, ignore=shutil.ignore_patterns("expected", "lastmods.json"))
    return base


def test_the_golden_fixture_holds_the_smoke_run():
    expected = GOLDEN / "expected" / "answers.jsonl"
    answers = [json.loads(x) for x in expected.read_text(encoding="utf-8").splitlines() if x]
    assert len(answers) == 20 and {a["run"] for a in answers} == {0}
    assert len({a["model"] for a in answers}) == 2


def test_replaying_the_smoke_run_gives_byte_identical_outputs(study: Path):
    cfg = load_study_config(study / "study.yaml")
    qs = load_questions(study / cfg.questions_path, cfg)
    run_extract(study, cfg, qs)
    for name in ("answers.jsonl", "citations.jsonl", "consulted.jsonl"):
        got = (study / "data" / name).read_bytes()
        assert got == (GOLDEN / "expected" / name).read_bytes(), name
    cited = [
        json.loads(x)["url"]
        for x in (study / "data" / "citations.jsonl").read_text(encoding="utf-8").splitlines()
        if x
    ]
    lastmods = json.loads((GOLDEN / "lastmods.json").read_text(encoding="utf-8"))
    write_page_meta(study, build_page_meta(study, list(dict.fromkeys(cited)), lastmods))
    got = (study / "data" / "page_meta.jsonl").read_bytes()
    assert got == (GOLDEN / "expected" / "page_meta.jsonl").read_bytes()
    out = write_summary(study, build_summary(study, cfg, qs, [0]))
    assert out.read_bytes() == (GOLDEN / "expected" / "summary.json").read_bytes()
