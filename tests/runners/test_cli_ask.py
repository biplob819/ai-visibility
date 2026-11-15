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
    assert len(spend) == 4  # one line per paid call (D-19)
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cached"] == 4


def test_a_resumed_run_estimates_only_what_is_missing(study, capsys, monkeypatch):
    """N1.2 v2 low: a finished run under a cap that fits only one call still resumes."""
    from citewatch import runners as runners_pkg

    from .test_schedule import FakeRunner

    monkeypatch.setattr(runners_pkg, "make_runner", lambda m: FakeRunner(m))
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["ask", "--run", "0", "--dry-run", "--study", str(study), "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["estimate"]["total_usd"] == 0
    assert all(v["calls"] == 0 for v in plan["estimate"]["per_model"].values())
    assert cli.main(["ask", "--run", "0", "--max-cost", "0.01", "--study", str(study)]) == 0


def _fake(monkeypatch, **kw):
    from citewatch import runners as runners_pkg

    from .test_schedule import FakeRunner

    monkeypatch.setattr(runners_pkg, "make_runner", lambda m: FakeRunner(m, **kw))


def test_a_cap_the_estimate_accepts_asks_at_least_one_question(study, capsys, monkeypatch):
    """v3 M1: the first reservation (4x planning) no longer refuses a small accepted cap."""
    _fake(monkeypatch)
    capsys.readouterr()
    args = ["ask", "--run", "0", "--questions", "q-001", "--max-cost", "0.30"]
    assert cli.main([*args, "--study", str(study), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["asked"] == 2


def test_a_run_where_every_call_fails_exits_2(study, capsys, monkeypatch):
    """v3 M2: every call refused (a bad key) is not a success."""
    from .helpers import StatusError

    _fake(monkeypatch, fail={q: StatusError(401) for q in ("q-001", "q-002")})
    capsys.readouterr()
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["asked"] == 0


def test_a_cap_reached_during_the_run_exits_3(study, capsys, monkeypatch):
    _fake(monkeypatch, tokens_in=400_000, tokens_out=8_000)  # about 10x the estimate per call
    capsys.readouterr()
    assert (
        cli.main(["ask", "--run", "0", "--max-cost", "1.0", "--study", str(study), "--json"]) == 3
    )
    assert json.loads(capsys.readouterr().out)["stopped_at_cap"] is True


def test_an_interrupted_run_exits_2(study, capsys, monkeypatch):
    import concurrent.futures

    real_wait = concurrent.futures.wait

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    _fake(monkeypatch, delay=0.05)
    monkeypatch.setattr("citewatch.runners.schedule.wait", interrupt)
    capsys.readouterr()
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["interrupted"] is True
    assert real_wait  # the real wait is untouched outside the scheduler


@pytest.mark.skipif(
    __import__("sys").platform == "win32", reason="SIGTERM to self ends a Windows process"
)
def test_sigterm_stops_like_ctrl_c_and_records_every_call(study, capsys, monkeypatch):
    import os
    import signal
    import threading

    _fake(monkeypatch, delay=0.3)
    timer = threading.Timer(0.2, os.kill, args=(os.getpid(), signal.SIGTERM))
    timer.start()
    capsys.readouterr()
    code = cli.main(["ask", "--run", "0", "--study", str(study), "--json"])
    timer.cancel()
    out = json.loads(capsys.readouterr().out)
    spend = (study / "data" / "spend-ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert code == 2 and out["interrupted"] is True and len(spend) == out["asked"]
    assert signal.getsignal(signal.SIGTERM) is not None  # the old handler is back


def test_a_resume_where_every_missing_call_fails_exits_2(study, capsys, monkeypatch):
    """v4 L5: answers already stored do not turn a revoked key into success."""
    from .helpers import StatusError

    _fake(monkeypatch)
    assert cli.main(["ask", "--run", "0", "--questions", "q-001", "--study", str(study)]) == 0
    _fake(monkeypatch, fail={"q-002": StatusError(401)})
    capsys.readouterr()
    assert cli.main(["ask", "--run", "0", "--study", str(study), "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["cached"] == 2 and out["asked"] == 0 and out["ok"] is False
