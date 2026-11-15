import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import status
from harness_lib import ROOT, load_catalog

WORKFLOWS = ROOT / ".github" / "workflows"
SPEC = ROOT / "AI Visibility Tech Spec.md"


def test_decisions_seeded_d1_to_d25():
    text = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    ids = {int(n) for n in re.findall(r"^\| (?:OWNER )?D-(\d+) \|", text, re.M)}
    assert set(range(1, 26)) <= ids


def test_lessons_seeded_and_changelog_has_w01():
    lessons = (ROOT / "docs" / "lessons.md").read_text(encoding="utf-8")
    ids = {int(n) for n in re.findall(r"^\| L-(\d+) \|", lessons, re.M)}
    assert set(range(1, 13)) <= ids
    assert "[W0.1]" in (ROOT / "changelog.md").read_text(encoding="utf-8")


def test_catalog_holds_every_spec_capability_once():
    spec = SPEC.read_text(encoding="utf-8")
    section = spec[spec.index("### 12.4 Capability catalog") : spec.index("### 12.5")]
    spec_caps = re.findall(r"^\| ([A-Z]{3}-\d\d) \|", section, re.M)
    cat_caps = [c.cap_id for c in load_catalog()]
    assert len(cat_caps) == len(set(cat_caps))
    assert sorted(cat_caps) == sorted(spec_caps)


def test_status_prints_graph_and_node(capsys):
    assert status.main([]) == 0
    out = capsys.readouterr().out
    assert "W0.1" in out and "D5.3" in out and "capabilities green" in out
    assert status.main(["W0.1"]) == 0
    assert "HAR-07" in capsys.readouterr().out
    assert status.main(["Z9.9"]) == 1


def test_status_output_is_deterministic(capsys):
    status.main([])
    first = capsys.readouterr().out
    status.main([])
    assert capsys.readouterr().out == first


def test_catalog_round_trip_is_byte_identical(tmp_path):
    from harness_lib import CATALOG_TSV, write_catalog

    out = tmp_path / "catalog.tsv"
    write_catalog(load_catalog(), out)
    assert out.read_bytes() == CATALOG_TSV.read_bytes()


def _yaml_code(path: Path) -> str:
    """Workflow text with comment-only lines and trailing comments removed."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        code = line.split(" #", 1)[0].rstrip()
        if code.strip() and not code.lstrip().startswith("#"):
            lines.append(code)
    return "\n".join(lines)


def test_ci_workflow_covers_gates_and_matrix():
    ci = _yaml_code(WORKFLOWS / "ci.yml")
    assert re.search(r"^on:\n  push:", ci, re.M)
    assert "pull_request" in ci
    for step in (
        "ruff check",
        "ruff format --check",
        "pyright",
        "pytest",
        "secret_scan.py",
        "storage_audit.py",
        "fetch_audit.py",
        "verify_graph_eligibility.py",
        "uv build",
    ):
        assert step in ci, step
    for v in ('"3.11"', '"3.12"', '"3.13"'):
        assert v in ci
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in ci


@pytest.mark.contract
def test_ci_grants_least_privilege():
    ci = _yaml_code(WORKFLOWS / "ci.yml")
    assert re.search(r"^permissions:\n  contents: read$", ci, re.M)
    assert "secrets." not in ci


def test_gitattributes_force_lf():
    assert "* text=auto eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


@pytest.mark.safety
def test_env_files_are_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored


def test_verifier_prompt_sets_the_rules():
    text = (ROOT / "docs" / "harness" / "verifier-prompt.md").read_text(encoding="utf-8")
    for needle in (
        "UV_PROJECT_ENVIRONMENT",
        "CONFIRMED",
        "DISPROVED",
        "criteria",
        "Never spend money",
        "never push",
    ):
        assert needle in text, needle
    assert "builder's reasoning" in text


def test_every_harness_script_self_test_passes():
    for script in (
        "verify_graph_eligibility.py",
        "node_start.py",
        "secret_scan.py",
        "fetch_audit.py",
        "storage_audit.py",
    ):
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--self-test"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        assert p.returncode == 0 and "PASSED" in p.stdout, (script, p.stdout, p.stderr)


@pytest.mark.safety
def test_job_search_content_stays_out_of_the_public_repo():
    assert "Portfolio notes.md" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for doc in ("AI Visibility PRD.md", "AI Visibility Tech Spec.md", "README.md"):
        text = (ROOT / doc).read_text(encoding="utf-8").lower()
        for needle in ("job hunt", "hiring manager", "greenhouse.io", "claude.ai/artifact"):
            assert needle not in text, (doc, needle)
