import json
import os
import shutil

import pytest

from citewatch import cli
from citewatch.env import MissingKeyError, key_for, key_status, load_dotenv
from harness_lib import ROOT

FLAGSHIP = ROOT / "studies" / "uk-health"


def run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def no_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env


@pytest.mark.contract
def test_help_lists_every_command(capsys):
    code, out, _ = run(["--help"], capsys)
    assert code == 0
    for c in ("init", "doctor", "ask", "extract", "fetch", "score", "report"):
        assert c in out


@pytest.mark.contract
@pytest.mark.parametrize(
    ("argv", "node"),
    [
        (["score"], "M3.1"),
        (["report", "--example"], "B4.1"),
    ],
)
def test_unbuilt_commands_exit_2_naming_their_node(capsys, argv, node):
    code, out, _ = run([*argv, "--json"], capsys)
    assert code == 2
    payload = json.loads(out)
    assert payload["ok"] is False and node in payload["error"]


@pytest.mark.parametrize("cap", ["0", "-1", "nan", "inf"])
def test_max_cost_must_be_positive(capsys, cap):
    code, _, _ = run(["ask", "--max-cost", cap], capsys)
    assert code == 2


def test_usage_errors_and_crashes_exit_2_with_one_line(capsys, monkeypatch):
    code, _, err = run(["ask", "--run", "7"], capsys)
    assert code == 2 and "run" in err and "Traceback" not in err
    code, _, err = run(["no-such-command"], capsys)
    assert code == 2

    def boom(*_a, **_k):
        raise RuntimeError("planted")

    monkeypatch.setattr(cli, "load_study_config", boom)
    code, _, err = run(["doctor", "--study", str(FLAGSHIP)], capsys)
    assert code == 2 and err.strip().count("\n") == 0 and "planted" in err


def test_bare_command_shows_help_and_exits_0(capsys):
    code, out, err = run([], capsys)
    assert code == 0 and "Usage" in out and err == ""


@pytest.mark.onboarding
def test_doctor_without_keys_exits_2_naming_variables_not_values(capsys, no_keys):
    code, out, _ = run(["doctor", "--study", str(FLAGSHIP), "--json"], capsys)
    assert code == 2
    checks = {c["check"]: c for c in json.loads(out)["checks"]}
    assert checks["ANTHROPIC_API_KEY"]["detail"] == "missing"
    assert checks["OPENAI_API_KEY"]["ok"] is False


@pytest.mark.safety
def test_doctor_never_prints_key_values(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    secret_a, secret_o = "sk-ant-" + "Z" * 40, "sk-proj-" + "Y1" * 20
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret_a)
    monkeypatch.setenv("OPENAI_API_KEY", secret_o)
    for flag in ([], ["--json"]):
        code, out, err = run(["doctor", "--study", str(FLAGSHIP), *flag], capsys)
        assert code == 0
        assert secret_a not in out + err and secret_o not in out + err


@pytest.mark.onboarding
def test_doctor_without_a_study_points_to_init(capsys, no_keys, tmp_path):
    code, out, _ = run(["doctor", "--study", str(tmp_path / "missing")], capsys)
    assert code == 2 and "citewatch init" in out


def test_doctor_flags_a_bad_user_agent(capsys, no_keys, tmp_path):
    study = tmp_path / "s"
    shutil.copytree(FLAGSHIP, study)
    text = (study / "study.yaml").read_text(encoding="utf-8")
    (study / "study.yaml").write_text(
        text.replace("(+https://github.com/biplob819/ai-visibility)", "(contact: me)"),
        encoding="utf-8",
    )
    code, out, _ = run(["doctor", "--study", str(study)], capsys)
    assert code == 2 and "user_agent" in out


@pytest.mark.onboarding
def test_init_creates_a_valid_study_and_refuses_to_overwrite(
    capsys, no_keys, tmp_path, monkeypatch
):
    target = tmp_path / "new-study"
    code, out, _ = run(["init", str(target), "--json"], capsys)
    assert code == 0
    created = json.loads(out)["created"]
    assert {os.path.basename(p) for p in created} == {
        "study.yaml",
        "questions.jsonl",
        "RUBRIC.md",
        ".env.example",
    }
    from citewatch.schemas import ConfigError, load_questions, load_study_config

    with pytest.raises(ConfigError, match="placeholder"):  # the template must be edited first
        load_study_config(target / "study.yaml")
    y = target / "study.yaml"
    y.write_text(
        y.read_text(encoding="utf-8").replace(
            "https://example.org/your-study", "https://github.com/me/my-study"
        ),
        encoding="utf-8",
    )
    cfg = load_study_config(y)
    assert len(load_questions(target / "questions.jsonl", cfg)) == 2
    (target / "questions.jsonl").write_text("mine\n", encoding="utf-8")
    code, out, _ = run(["init", str(target)], capsys)
    assert code == 2 and "refusing to overwrite" in out
    assert (target / "questions.jsonl").read_text(encoding="utf-8") == "mine\n"


def test_dotenv_loads_without_overriding_and_returns_names_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nexport ANTHROPIC_API_KEY='abc'\nOPENAI_API_KEY=real\nEMPTY=\n", encoding="utf-8"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    monkeypatch.delenv("EMPTY", raising=False)
    loaded = load_dotenv(env)
    assert set(loaded) == {"ANTHROPIC_API_KEY", "EMPTY"}
    assert os.environ["ANTHROPIC_API_KEY"] == "abc"
    assert os.environ["OPENAI_API_KEY"] == "from-shell"
    assert key_status(["anthropic", "openai"]) == {
        "ANTHROPIC_API_KEY": True,
        "OPENAI_API_KEY": True,
    }


def test_missing_key_names_the_variable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="OPENAI_API_KEY"):
        key_for("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    with pytest.raises(MissingKeyError):
        key_for("openai")
