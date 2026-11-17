"""OSS-03: `citewatch init` never overwrites anything, and a study of someone else's (its own
intents, another country, one provider) plans its run with `ask --dry-run` and no keys."""

from __future__ import annotations

import json
import os

import pytest
import yaml

from citewatch import cli
from citewatch.cli import TEMPLATES
from citewatch.schemas import load_questions, load_study_config

pytestmark = pytest.mark.onboarding


@pytest.fixture
def no_keys(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env


def run(argv, capsys):
    capsys.readouterr()
    code = cli.main(argv)
    return code, capsys.readouterr().out


@pytest.mark.parametrize("existing", sorted(TEMPLATES))
def test_init_overwrites_no_file_and_creates_none_beside_one(no_keys, tmp_path, capsys, existing):
    """Any one of the four files already there: init refuses, leaves it byte for byte, and
    writes none of the other three either."""
    target = tmp_path / "study"
    target.mkdir()
    (target / existing).write_bytes(b"mine\r\n")
    code, out = run(["init", str(target), "--json"], capsys)
    assert code == 2 and json.loads(out)["error"].startswith("refusing to overwrite")
    assert existing in json.loads(out)["error"]
    assert (target / existing).read_bytes() == b"mine\r\n"
    assert sorted(os.listdir(target)) == [existing]


def test_init_refuses_a_dangling_symlink(no_keys, tmp_path, capsys):
    target = tmp_path / "study"
    target.mkdir()
    try:
        (target / "study.yaml").symlink_to(tmp_path / "elsewhere.yaml")
    except OSError:  # Windows without symlink rights
        pytest.skip("symlinks are not available")
    code, out = run(["init", str(target)], capsys)
    assert code == 2 and "refusing to overwrite" in out
    assert not (tmp_path / "elsewhere.yaml").exists()  # nothing written through the link


def test_init_twice_changes_nothing(no_keys, tmp_path, capsys):
    target = tmp_path / "study"
    assert run(["init", str(target), "--contact", "https://github.com/me/s"], capsys)[0] == 0
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    code, out = run(["init", str(target), "--contact", "https://github.com/other/s"], capsys)
    assert code == 2 and "refusing to overwrite" in out
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before


QUESTIONS = [
    {
        "id": "de-001",
        "text": "Wie beantrage ich einen Reisepass?",
        "intent": "documents",
        "time_sensitive": False,
    },
    {
        "id": "de-002",
        "text": "Was kostet ein Reisepass im Moment?",
        "intent": "fees",
        "time_sensitive": True,
        "ts_reason": "prices",
    },
    {
        "id": "de-003",
        "text": "Wo melde ich meinen Wohnsitz an?",
        "intent": "registration",
        "time_sensitive": False,
    },
]


@pytest.fixture
def own_study(no_keys, tmp_path, capsys):
    """A German civic-services study on one provider, made from `init`'s templates."""
    target = tmp_path / "de-civic"
    assert run(["init", str(target), "--contact", "https://github.com/me/de-civic"], capsys)[0] == 0
    path = target / "study.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg.update(
        name="de-civic",
        intents=["documents", "fees", "registration"],
        ts_reasons=["prices"],
        models=["gpt-6.1-sol"],
        user_location={"type": "approximate", "country": "DE", "city": "Berlin"},
        max_cost_usd=2,
    )
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    (target / "questions.jsonl").write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in QUESTIONS), encoding="utf-8"
    )
    return target


def test_a_custom_study_loads_with_its_own_intents_country_and_model(own_study):
    cfg = load_study_config(own_study / "study.yaml")
    assert cfg.models == ("gpt-6.1-sol",) and cfg.user_location.country == "DE"
    assert [q.intent for q in load_questions(own_study / "questions.jsonl", cfg)] == [
        "documents",
        "fees",
        "registration",
    ]


@pytest.mark.parametrize("run_no", [0, 1])
def test_a_custom_one_provider_study_dry_runs_with_no_keys(own_study, capsys, run_no):
    code, out = run(
        ["ask", "--run", str(run_no), "--dry-run", "--study", str(own_study), "--json"], capsys
    )
    assert code == 0, out
    plan = json.loads(out)
    assert plan["dry_run"] is True and plan["questions"] == 3
    assert plan["models"] == ["gpt-6.1-sol"]
    assert list(plan["estimate"]["per_model"]) == ["gpt-6.1-sol"]
    assert plan["estimate"]["per_model"]["gpt-6.1-sol"]["calls"] == 3
    assert plan["cap_usd"] == 2
    assert not (own_study / "data").exists()  # nothing asked, nothing stored


def test_doctor_asks_only_for_the_one_providers_key(own_study, capsys):
    code, out = run(["doctor", "--study", str(own_study), "--json"], capsys)
    checks = {c["check"]: c for c in json.loads(out)["checks"]}
    assert code == 2 and checks["OPENAI_API_KEY"]["ok"] is False
    assert "ANTHROPIC_API_KEY" not in checks  # a provider the study does not use
    assert checks["study"]["ok"] is True
