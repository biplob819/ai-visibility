import json

import pytest

from citewatch import cli


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["init", "s", "--contact", "https://github.com/me/study"]) == 0
    return tmp_path / "s"


@pytest.mark.onboarding
def test_dry_run_needs_no_keys_and_prints_the_estimate(study, capsys):
    capsys.readouterr()
    assert cli.main(["ask", "--run", "0", "--dry-run", "--study", str(study), "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["questions"] == 2 and plan["estimate"]["total_usd"] > 0 and plan["dry_run"] is True


def test_an_estimate_over_the_cap_stops_before_any_call(study, capsys):
    capsys.readouterr()
    assert (
        cli.main(["ask", "--run", "0", "--max-cost", "0.01", "--study", str(study), "--json"]) == 3
    )
    assert "nothing was asked" in json.loads(capsys.readouterr().out)["error"]
    assert not (study / "data").exists()


def test_a_real_ask_without_keys_names_the_variable(study, capsys):
    capsys.readouterr()
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 2
    assert "API_KEY" in json.loads(capsys.readouterr().out)["error"]


def test_unknown_question_ids_are_refused(study, capsys):
    assert cli.main(["ask", "--dry-run", "--questions", "q-001,q-999", "--study", str(study)]) == 2


def test_init_contact_is_validated_and_written(study, tmp_path, capsys):
    text = (study / "study.yaml").read_text(encoding="utf-8")
    assert "https://github.com/me/study" in text and "example.org" not in text
    assert cli.main(["init", "t", "--contact", "https://example.org/x"]) == 2
    assert not (tmp_path / "t" / "study.yaml").exists()


def test_a_full_run_with_fake_runners_records_spend_and_order(study, capsys, monkeypatch):
    from citewatch import runners as runners_pkg

    from .test_schedule import FakeRunner

    monkeypatch.setattr(runners_pkg, "make_runner", lambda m: FakeRunner(m))
    capsys.readouterr()
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["asked"] == 4 and out["spent_usd"] > 0
    assert (study / "data" / "runs" / "run-0" / "order.json").is_file()
    spend = (study / "data" / "spend-ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(spend) == 1
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cached"] == 4
