"""DSH-03 (OWNER D-70): the dashboard is published by .github/workflows/pages.yml, built from
the committed summary with the same command a reader can run, and the build is deterministic."""

from __future__ import annotations

from pathlib import Path

import yaml

from citewatch.report import render
from citewatch.schemas import StudySummary

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
COMMAND = 'uv run citewatch report --study studies/uk-health --title "UK health"'


def _flow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_builds_the_dashboard_and_publishes_only_the_site():
    steps = _flow()["jobs"]["build"]["steps"]
    runs = [s.get("run") for s in steps]
    assert COMMAND in runs
    upload = next(
        s for s in steps if str(s.get("uses", "")).startswith("actions/upload-pages-artifact")
    )
    assert upload["with"]["path"] == "studies/uk-health/results/site"
    deploy = _flow()["jobs"]["deploy"]["steps"]
    assert any(str(s.get("uses", "")).startswith("actions/deploy-pages") for s in deploy)


def test_the_workflow_asks_only_for_the_permissions_pages_needs():
    flow = _flow()
    assert flow["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    triggers = flow.get("on") or flow.get(True)  # YAML reads a bare `on` key as True
    assert isinstance(triggers, dict)
    assert triggers["push"]["branches"] == ["main"]
    assert "studies/uk-health/results/summary.json" in triggers["push"]["paths"]


def test_the_published_page_is_a_pure_function_of_the_committed_summary():
    text = (ROOT / "studies" / "uk-health" / "results" / "summary.json").read_text("utf-8")
    a = render(StudySummary.model_validate_json(text), "UK health")
    b = render(StudySummary.model_validate_json(text), "UK health")
    assert a == b
