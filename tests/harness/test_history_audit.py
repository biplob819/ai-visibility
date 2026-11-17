"""REL-02: the full-history audit finds what it must, and the real history is clean."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _audit():
    spec = importlib.util.spec_from_file_location(
        "history_audit", ROOT / "scripts" / "history_audit.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo(tmp: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for args in (
        ["add", "-A"],
        ["-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "x"],
    ):
        subprocess.run(["git", *args], cwd=tmp, check=True)
    return tmp


@pytest.mark.safety
def test_the_audit_catches_each_kind_of_problem_even_if_later_deleted(tmp_path: Path, monkeypatch):
    fake_key = "sk-ant-api03-" + "Q7x" * 30
    repo = _repo(
        tmp_path,
        {
            "notes.txt": f"key = {fake_key}\n",
            ".env": "X=1\n",
            "studies/s/data/page.jsonl": '{"html": "<!doctype html><html><body>page</body>"}\n',
            "docs/plan.md": "apply via boards.greenhouse.io/x\n",
            "studies/s/data/ok.jsonl": '{"url": "https://e.org"}\n',
        },
    )
    subprocess.run(["git", "rm", "-q", ".env", "notes.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "rm"],
        cwd=repo,
        check=True,
    )
    mod = _audit()
    monkeypatch.setattr(mod, "ROOT", repo)
    problems, stats = mod.findings()
    text = "\n".join(problems)
    assert stats["commits"] == 2
    assert ".env: a .env file was committed" in text
    assert "notes.txt" in text and "possible" in text
    assert "HTML document marker in study data" in text
    assert "job-search marker 'greenhouse.io'" in text
    assert "ok.jsonl" not in text


@pytest.mark.safety
def test_an_env_example_is_allowed_and_a_named_env_file_is_not():
    mod = _audit()
    assert not mod.ENV_PATH.search(".env.example")
    assert mod.ENV_PATH.search("demo/.env") and mod.ENV_PATH.search(".env.local")


@pytest.mark.safety
def test_the_repository_history_is_clean():
    """OWNER D-21: the repo is public, so every past file version is checked."""
    problems, stats = _audit().findings()
    assert problems == []
    assert stats["commits"] >= 1
