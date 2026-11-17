"""REL-02: the full-history audit finds what it must, and the real history is clean.

Planted values are built by concatenation so this file itself never matches a secret pattern, a
job-search marker or a private link.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
WHO = ["-c", "user.email=a@b.c", "-c", "user.name=t"]

FAKE_SECRETS = {
    "anthropic key": "key = " + "sk-ant-api03-" + "Q7x" * 30,
    "google api key": "maps = " + "AIza" + "Sy" + "A1b2C3d4E5" * 3 + "xyz",
    "slack token": "hook = " + "xox" + "b-" + "1234567890-" + "AbCdEf123456",
    "upstash token": "UPSTASH_REDIS_REST_" + "TOKEN=" + "AXy1" * 10,
    "upstash redis url": "url = rediss://default:" + "Qw3rTy" * 4 + "@eu1-x.upstash" + ".io:6379",
    "upstash rest url": "u = https://eu1-x.upstash" + ".io/get/k?_token=" + "Zx9" * 8,
    "secret assignment": "db_pass" + 'word = "' + "Zq8Lm3Xw9Pk2Rt7Vb4Nc6Hy" + '"',
    "pypi token": "pypi" + "-" + "AgEIcHlwaS5vcmc" * 4,
    "hugging face token": "hf" + "_" + "aBcD1234eFgH5678" * 2,
    "private key": "-----BEGIN " + "PRIVATE KEY-----",
}
JOB_LINES = {
    "greenhouse": "apply via boards.green" + "house.io/x",
    "hiring_manager": "ping the hiring " + "manager on Monday",
    "linkedin": "see linkedin.com/" + "in/someone",
    "employee_referral": "ask for an employee " + "referral",
    "recruit": "the recruit" + "er called back",
    "job_application": "track the job " + "application",
    "outreach_tracker": "update the outreach " + "tracker",
    "cover_letter": "draft the cover " + "letter",
}
PRIVATE = (
    "https://docs.google" + ".com/document/d/1AbC/edit",
    "https://team.notion" + ".so/Plan-123",
    "https://claude.ai/" + "artifact/NewPage123",
)


def _audit() -> Any:
    spec = importlib.util.spec_from_file_location(
        "history_audit", ROOT / "scripts" / "history_audit.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, *WHO, "commit", "-qm", "x")
    return tmp


RULE_LINE = "OWNER D-22: no hiring " + "manager names here"
ENV_FILES = (
    ".env",
    "config/prod.env",
    ".envrc",
    ".streamlit/secrets.toml",
    "certs/server.pem",
    "keys/id_rsa",
    "keys/id_rsa.pub",
)
BIG_PAGE = "<!doctype html><html><body>" + "<p>stored page text</p>" * 1200 + "</body></html>"
BODY_PAGE = "notes\n<body>\n" + "a saved article sentence. " * 120 + "\n</body>\n"
LONG = "x" * 3000


@pytest.fixture(scope="module")
def planted(tmp_path_factory: pytest.TempPathFactory):
    """Two commits: the first plants every problem, the second deletes them all."""
    tmp = tmp_path_factory.mktemp("hist")
    files = {
        "notes.txt": "\n".join(FAKE_SECRETS.values()) + "\n",
        ".env.example": "ANTHROPIC_API_KEY=\n",
        "studies/s/data/page.jsonl": '{"html": "<!doctype html><html><body>page</body>"}\n',
        "studies/s/data/ok.jsonl": '{"url": "https://e.org", "text": "short quote"}\n',
        "studies/s/data/long_text.jsonl": '{"text": "' + LONG + '"}\n',
        "studies/s/results/long_content.json": '{"rows": [{"content": "' + LONG + '"}]}\n',
        "data/long_main.jsonl": '{"main_text": "' + LONG + '"}\n',
        "docs/plan.md": "\n".join(JOB_LINES.values()) + "\n",
        "docs/links.md": "\n".join(PRIVATE) + "\nhttps://claude.ai/" + "artifact/KnownPage1\n",
        "tests/test_x.py": "# the hiring " + "manager is Jo\n",
        "scripts/tool.py": "# recruit" + "er: Jo\n",
        "AI Visibility PRD.md": "US6\ncover " + "letter draft\n",
        "AI Visibility Tech Spec.md": "job " + "application status\n",
        "docs/decisions.md": RULE_LINE + "\n" + "outreach " + "tracker row 3\n",
        "docs/page.html": BIG_PAGE,
        "docs/saved.md": BODY_PAGE,
        "docs/cut.md": "<html><head></head><body><article>" + "Words of a saved page. " * 600,
        "tests/fixtures/dates/pages/sub/deep.html": BODY_PAGE,
        "studies/s/data/plant.csv": "url,body\nhttps://e.org,a page\n",
        "studies/s/data/long.ndjson": '{"page_content": "' + "x" * 3000 + '"}\n',
        "tests/fixtures/dates/pages/ok.html": "<html><body><time>2024</time></body></html>",
        "tests/fixtures/dates/pages/big.html": BIG_PAGE,
        "docs/signal-spec.html": "<!doctype html><html><body>spec</body></html>",
        **{name: "X=1\n" for name in ENV_FILES},
    }
    repo = _repo(tmp, files)
    keep = {"studies/s/data/ok.jsonl", ".env.example"}
    _git(repo, "rm", "-q", "--", *sorted(set(files) - keep))
    _git(
        repo,
        "-c",
        "user.email=jo.recruit" + "er@corp.example",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        "rm\n\nsee the outreach " + "tracker; " + FAKE_SECRETS["hugging face token"],
    )
    _git(repo, *WHO, "tag", "-a", "v1", "-m", "release " + FAKE_SECRETS["slack token"])
    return repo


@pytest.fixture(scope="module")
def result(planted: Path):
    mod = _audit()
    mod.ROOT = planted
    mod.LINE_ALLOW = {("docs/decisions.md", mod.line_key(RULE_LINE)): "states the rule"}
    mod.KNOWN_PRIVATE_LINKS = {"https://claude.ai/" + "artifact/KnownPage1": "reviewed"}
    rep = mod.report()
    return rep, "\n".join(rep.problems), "\n".join(rep.private)


def _lines(text: str, path: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(path + " ")]


@pytest.mark.safety
def test_both_commits_are_audited(result):
    rep, _, _ = result
    assert rep.stats["commits"] == 2


@pytest.mark.safety
@pytest.mark.parametrize("name", ENV_FILES)
def test_every_secret_bearing_path_is_caught_after_deletion(result, name):
    _, text, _ = result
    assert f"{name}: a secret-bearing file" in text
    assert ".env.example:" not in text


@pytest.mark.safety
@pytest.mark.parametrize("kind", sorted(FAKE_SECRETS))
def test_every_secret_kind_is_caught_after_deletion(result, kind):
    _, text, _ = result
    lineno = list(FAKE_SECRETS).index(kind) + 1
    hits = [h for h in _lines(text, "notes.txt") if f":{lineno}: possible " in h]
    assert hits, kind


@pytest.mark.safety
@pytest.mark.parametrize("marker", sorted(JOB_LINES))
def test_every_job_marker_is_caught_after_deletion(result, marker):
    _, text, _ = result
    lineno = list(JOB_LINES).index(marker) + 1
    assert any(f":{lineno}: job-search marker" in h for h in _lines(text, "docs/plan.md")), marker


@pytest.mark.safety
@pytest.mark.parametrize(
    "path",
    ["tests/test_x.py", "scripts/tool.py", "AI Visibility PRD.md", "AI Visibility Tech Spec.md"],
)
def test_tests_scripts_and_rule_docs_are_no_longer_exempt(result, path):
    _, text, _ = result
    assert any("job-search marker" in h for h in _lines(text, path)), path


@pytest.mark.safety
def test_only_the_exact_allow_listed_line_passes_in_decisions(result):
    _, text, _ = result
    hits = _lines(text, "docs/decisions.md")
    assert len(hits) == 1 and ":2: job-search marker 'outreach " + "tracker'" in hits[0]


@pytest.mark.safety
def test_private_links_are_reported_but_do_not_fail(result):
    _, text, private = result
    for link in PRIVATE:
        assert link in private
    assert "KnownPage1" not in private and "private link" not in text


@pytest.mark.safety
def test_full_html_pages_are_caught_anywhere_but_the_named_fixtures(result):
    _, text, _ = result
    assert "an HTML document of" in "\n".join(_lines(text, "docs/page.html"))
    assert "a <body> with" in "\n".join(_lines(text, "docs/saved.md"))
    assert _lines(text, "tests/fixtures/dates/pages/big.html")  # over the fixture size cap
    assert not _lines(text, "tests/fixtures/dates/pages/ok.html")
    assert not _lines(text, "docs/signal-spec.html")


@pytest.mark.safety
def test_study_html_and_long_body_values_are_caught(result):
    _, text, _ = result
    assert "HTML document marker in study data" in "\n".join(
        _lines(text, "studies/s/data/page.jsonl")
    )
    for path, key in (
        ("studies/s/data/long_text.jsonl", "text"),
        ("studies/s/results/long_content.json", "content"),
        ("data/long_main.jsonl", "main_text"),
    ):
        assert f"long page-body value {key} (" in "\n".join(_lines(text, path)), path
    assert "ok.jsonl" not in text


@pytest.mark.safety
def test_commit_messages_tag_messages_and_identities_are_checked(result):
    _, text, _ = result
    assert any(
        h.startswith("commit ") and " message:" in h and "outreach " + "tracker" in h
        for h in text.splitlines()
    )
    assert any(
        h.startswith("commit ") and " message:" in h and "hugging face token" in h
        for h in text.splitlines()
    )
    assert any(h.startswith("commit ") and " identity:" in h for h in text.splitlines())
    assert "tag v1 message:1: possible slack token" in text


@pytest.mark.safety
def test_an_env_example_is_allowed_and_a_named_env_file_is_not():
    mod = _audit()
    assert not mod.ENV_PATH.search(".env.example")
    assert mod.ENV_PATH.search("demo/.env") and mod.ENV_PATH.search(".env.local")


@pytest.mark.safety
def test_names_and_env_references_are_not_secret_assignments():
    import secret_scan

    for line in (
        'token = os.environ["UPSTASH_REDIS_REST_TOKEN"]',
        'API_KEY = "ANTHROPIC_API_KEY_NAME_GOES_HERE"',
        'password = "your-password-goes-here-1A"',
        'secret_path = "src/citewatch/fetch/robots.py"',
    ):
        assert secret_scan.line_hits(line) == [], line


@pytest.mark.safety
def test_ordinary_health_referrals_are_not_job_markers():
    mod = _audit()
    for line in ("Ask your GP for a " + "referral.", "self-" + "referral to physiotherapy"):
        assert not mod._JOB_RE.search(line), line


@pytest.mark.safety
def test_the_repository_history_is_clean():
    """OWNER D-21: the repo is public, so every past file version and message is checked."""
    problems, stats = _audit().findings()
    assert problems == []
    assert stats["commits"] >= 1


@pytest.mark.safety
def test_cut_off_pages_deep_fixtures_csv_bodies_and_other_keys_are_caught(result):
    """B4.4 pass 2: a page without </body> in a .md file, a fixture glob that crossed folders,
    a CSV body column, and long text under page_content in .ndjson."""
    _, text, _ = result
    for path in (
        "docs/cut.md",
        "tests/fixtures/dates/pages/sub/deep.html",
        "studies/s/data/plant.csv",
        "studies/s/data/long.ndjson",
    ):
        assert path in text, path
