"""THR-02: the example GitHub Actions workflow parses, its command exists, and it fails the
job (exit 1) on a failed threshold when run against committed study data."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import typer
import yaml

from citewatch.cli import app, main
from harness_lib import ROOT

WORKFLOW = ROOT / "examples" / "github-action" / "citewatch.yml"
DOC = ROOT / "docs" / "thresholds.md"


def workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def score_command() -> list[str]:
    runs = [
        s["run"]
        for job in workflow()["jobs"].values()
        for s in job["steps"]
        if "citewatch" in s.get("run", "")
    ]
    assert len(runs) == 1, runs
    argv = shlex.split(runs[0])
    return argv[argv.index("citewatch", argv.index("--from") + 2) + 1 :]


@pytest.mark.contract
def test_the_example_workflow_parses_and_has_no_secrets():
    data = workflow()
    triggers = data.get("on", data.get(True))  # YAML 1.1 reads the `on:` key as true
    assert isinstance(triggers, dict) and {"push", "pull_request"} <= set(triggers)
    assert data["permissions"] == {"contents": "read"}
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text and "API_KEY" not in text  # score needs no keys


@pytest.mark.contract
def test_the_example_command_and_its_options_exist():
    argv = score_command()
    assert argv[0] == "score"
    click_app = typer.main.get_command(app)
    score = click_app.commands["score"]  # type: ignore[attr-defined]
    known = {o for p in score.params for o in p.opts}
    used = [a for a in argv[1:] if a.startswith("--")]
    assert used and set(used) <= known


def test_the_example_command_fails_the_job_on_a_threshold(tiny: Path, capsys, monkeypatch):
    """The workflow's own argv, with $STUDY pointing at a study whose rule fails, exits 1."""
    path = tiny / "study.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "thresholds:\n  - metric: share:presence:nhs.uk:gpt-6.1-sol:run-1\n"
        + '    op: ">="\n    bound: 0.9\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDY", str(tiny))
    argv = [a.replace("$STUDY", str(tiny)) for a in score_command()]
    assert main(argv) == 1
    assert "FAIL share:presence:nhs.uk:gpt-6.1-sol:run-1" in capsys.readouterr().out
    path.write_text(path.read_text(encoding="utf-8").replace("0.9", "0.1"), encoding="utf-8")
    assert main(argv) == 0


def test_the_docs_list_every_selector_family():
    from citewatch.schemas.thresholds import FAMILIES

    text = DOC.read_text(encoding="utf-8")
    for family in FAMILIES:
        assert re.search(rf"`{family}[`:]", text), family
    assert "examples/github-action/citewatch.yml" in text
