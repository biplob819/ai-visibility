"""OSS-03, second half: a study of someone else's (its own intents, another country, one
provider) runs end to end through the real CLI on recorded fixtures: `init`, then `ask --run 1`
past the real gate G1, `extract`, `fetch`, `score` and `report`.

Nothing leaves the machine and no key is spent. The provider SDK is the real `openai` client,
built by the real `make_runner`, but its HTTP transport is an httpx2 MockTransport that replays
recorded Responses API bodies (tests/fixtures/providers). Cited pages and robots.txt come from a
second MockTransport behind the real PoliteClient (with a virtual clock, so the 1 s per host
spacing costs nothing). Any socket connection, real httpx/httpx2 transport or file write outside
tmp_path fails the test.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import httpx2  # the HTTP library the openai SDK is built on
import pytest
import yaml

from citewatch import cli
from citewatch import fetch as fetch_pkg
from citewatch.schemas import StudySummary
from tests.fetch.web import VClock, audit

pytestmark = pytest.mark.onboarding

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "providers"
MODEL = "gpt-6.1-sol"
DUMMY_KEY = "sk-test-not-a-real-key"  # never sent anywhere: the transport is mocked
INTENTS = ["fees", "fitness", "documents"]

# Custom questions, each answered by a recorded gpt-6.1-sol response (by fixture id).
QUESTIONS = [
    (
        {
            "id": "de-001",
            "text": "Was kostet ein Rezept in der Apotheke im Moment?",
            "intent": "fees",
            "time_sensitive": True,
            "ts_reason": "prices",
        },
        "v-901",
    ),
    (
        {
            "id": "de-002",
            "text": "Warum tun meine Beine nach einem langen Lauf weh?",
            "intent": "fitness",
            "time_sensitive": False,
        },
        "v-902",
    ),
    (
        {
            "id": "de-003",
            "text": "Welche Unterlagen brauche ich für einen neuen Reisepass?",
            "intent": "documents",
            "time_sensitive": False,
        },
        "v-901",
    ),
]

PAGE = (
    b"<html><head><title>Seite</title>"
    b'<meta property="article:modified_time" content="2026-10-01T09:00:00+00:00">'
    b"</head><body><p>Eine Seite mit Inhalt.</p></body></html>"
)


def recorded(fixture_id: str) -> dict[str, Any]:
    env = json.loads((FIX / f"{MODEL}--{fixture_id}.json").read_text(encoding="utf-8"))
    return copy.deepcopy(env["answer"]["raw"][-1])


# --- guards: no network, no writes outside tmp_path ---------------------------------------

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_watch: dict[str, Any] = {"root": None, "outside": []}


def _note(path: Any) -> None:
    root = _watch["root"]
    if root is None or isinstance(path, int) or path is None:
        return
    p = os.path.realpath(os.fsdecode(path)).removeprefix("\\\\?\\")  # Windows long-path form
    if "__pycache__" in p or p.startswith(root + os.sep) or p == root or p == os.devnull:
        return
    _watch["outside"].append(p)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if _watch["root"] is None:
        return
    if event == "open":
        path, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        ):
            _note(path)
    elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.truncate", "os.symlink", "os.link"}:
        _note(args[0])
    elif event in {"os.rename", "os.replace"}:
        _note(args[0])
        _note(args[1])
    elif event in {"shutil.copyfile", "shutil.move", "shutil.rmtree"}:
        _note(args[-1] if event != "shutil.rmtree" else args[0])


_hook_installed = False


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    """Fail on any real connection or any file written outside tmp_path."""
    global _hook_installed
    if not _hook_installed:  # audit hooks cannot be removed; this one is inert when unwatched
        sys.addaudithook(_audit)
        _hook_installed = True
    attempts: list[str] = []

    def refuse(what: str):
        def _refuse(*a: Any, **k: Any) -> Any:
            attempts.append(f"{what} {a[1:2] or a[:1]}")
            raise AssertionError(f"un-mocked network access: {what}")

        return _refuse

    monkeypatch.setattr(socket.socket, "connect", refuse("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", refuse("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("socket.getaddrinfo"))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse("httpx.HTTPTransport"))
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse("httpx2.HTTPTransport"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CITEWATCH_BODY_CACHE", str(tmp_path / "body-cache"))
    monkeypatch.chdir(tmp_path)  # no stray .env
    _watch["root"] = os.path.realpath(tmp_path).removeprefix("\\\\?\\")
    _watch["outside"] = []
    try:
        yield attempts
    finally:
        _watch["root"] = None
    assert attempts == [], attempts
    assert _watch["outside"] == [], _watch["outside"]


# --- fakes at the SDK and fetch boundaries ------------------------------------------------


class ProviderReplay:
    """The OpenAI Responses endpoint, replayed from recorded bodies keyed by question text."""

    def __init__(self) -> None:
        self.by_text: dict[str, dict[str, Any]] = {}
        for i, (q, fixture_id) in enumerate(QUESTIONS):
            body = recorded(fixture_id)
            body["id"] = f"{body['id']}-{i}"  # one response id per question
            self.by_text[q["text"]] = body
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        assert request.url.host == "api.openai.com" and request.url.path == "/v1/responses"
        assert request.headers["authorization"] == f"Bearer {DUMMY_KEY}"
        payload = json.loads(request.content)
        self.requests.append(payload)
        return httpx2.Response(200, json=self.by_text[payload["input"]])


class Web:
    """Every cited host: robots.txt allows all, every page is a small dated HTML page."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=PAGE
        )


@pytest.fixture
def replay(sealed, monkeypatch):
    import openai

    provider, web, clock = ProviderReplay(), Web(), VClock()
    real_openai, real_client = openai.OpenAI, fetch_pkg.PoliteClient

    def fake_openai(**kw: Any) -> Any:  # the real SDK, on a mocked transport
        return real_openai(
            **kw, http_client=httpx2.Client(transport=httpx2.MockTransport(provider.handler))
        )

    def fake_polite(ua: str, log: Any, **kw: Any) -> Any:  # the real client, on a fake web
        limiter = fetch_pkg.HostLimiter(clock=clock.now, sleep=clock.sleep, wall=clock.wall)
        return real_client(
            ua,
            log,
            transport=httpx.MockTransport(web.handler),
            limiter=limiter,
            sleep=clock.sleep,
            **kw,
        )

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", DUMMY_KEY)  # make_runner needs one; it goes nowhere
    monkeypatch.setattr(fetch_pkg, "PoliteClient", fake_polite)
    return provider, web


# --- the study ------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.org",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.org",
    }
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    )
    return out.stdout


def run(argv: list[str], capsys) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr().out
    return code, json.loads(out)


@pytest.fixture
def own_study(replay, tmp_path, capsys):
    """A German study on one provider, from `init`'s templates, ready for gate G1 except for
    its commit."""
    target = tmp_path / "de-study"
    code, _ = run(["init", str(target), "--contact", "https://github.com/me/de-study"], capsys)
    assert code == 0
    path = target / "study.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg.update(
        name="de-study",
        intents=INTENTS,
        ts_reasons=["prices"],
        models=[MODEL],
        user_location={
            "type": "approximate",
            "country": "DE",
            "city": "Berlin",
            "timezone": "Europe/Berlin",
        },
        max_cost_usd=2,
    )
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    questions = target / "questions.jsonl"
    questions.write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q, _ in QUESTIONS), encoding="utf-8"
    )
    # Gate G1's inputs: a frozen pre-registration, its hashes and the questions' in the
    # decisions log, a measured cost model and prices checked today (the study's own copy).
    prereg = target / "preregistration.md"
    prereg.write_text("# Pre-registration\n\nMetrics as defined by citewatch.\n", "utf-8")
    from citewatch.runs import sha256

    (target / "decisions.md").write_text(
        "# Decisions\n\n"
        f"- questions.jsonl sha256 {sha256(questions)}\n"
        f"- preregistration.md sha256 {sha256(prereg)}\n",
        encoding="utf-8",
    )
    (target / "cost_model.yaml").write_text(
        yaml.safe_dump({"models": {MODEL: {"tokens_in": 20000, "tokens_out": 600, "searches": 2}}}),
        encoding="utf-8",
    )
    from importlib.resources import files

    prices = yaml.safe_load(files("citewatch").joinpath("prices.yaml").read_text("utf-8"))
    mine = {MODEL: {**prices[MODEL], "checked_on": dt.date.today()}}
    (target / "prices.yaml").write_text(yaml.safe_dump(mine), encoding="utf-8")
    git(target, "init", "-q")
    return target


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_gate_g1_refuses_run_1_before_the_study_is_committed(own_study, replay, capsys):
    provider, web = replay
    code, out = run(["ask", "--run", "1", "--study", str(own_study)], capsys)
    assert code == 2 and "gate G1 refuses run 1" in out["error"]
    assert "not a git repository" in out["error"] or "uncommitted changes" in out["error"]
    assert provider.requests == [] and web.requests == []
    assert not (own_study / "data").exists()


def test_a_custom_one_provider_study_runs_end_to_end_on_recorded_fixtures(
    own_study, replay, capsys
):
    provider, web = replay
    git(own_study, "add", "-A")
    git(own_study, "commit", "-q", "-m", "freeze the study")
    sha = git(own_study, "rev-parse", "HEAD").strip()

    code, plan = run(["ask", "--run", "1", "--dry-run", "--study", str(own_study)], capsys)
    assert code == 0 and plan["gate"] == [], plan  # the real gate G1 passes

    code, out = run(["ask", "--run", "1", "--study", str(own_study)], capsys)
    assert code == 0, out
    assert out["asked"] == 3 and out["errors"] == [] and 0 < out["spent_usd"] < 2
    assert out["models"] == [MODEL]
    assert len(provider.requests) == 3
    for req in provider.requests:  # the study's own location and instruction reach the SDK
        assert req["model"] == MODEL
        assert req["tools"][0]["user_location"] == {
            "type": "approximate",
            "country": "DE",
            "city": "Berlin",
            "timezone": "Europe/Berlin",
        }
        assert req["instructions"].startswith("Answer for a reader in Germany")
    manifest = json.loads((own_study / "data/runs/run-1/manifest.json").read_text("utf-8"))
    assert manifest["git_sha"] == sha and manifest["answers"] == 3
    assert manifest["model_snapshots"] == {MODEL: [MODEL]}

    code, out = run(["extract", "--study", str(own_study)], capsys)
    assert code == 0, out
    answers = rows(own_study / "data" / "answers.jsonl")
    assert {(a["question_id"], a["model"], a["run"]) for a in answers} == {
        (q["id"], MODEL, 1) for q, _ in QUESTIONS
    }
    citations = rows(own_study / "data" / "citations.jsonl")
    assert citations and {c["question_id"] for c in citations} == {q["id"] for q, _ in QUESTIONS}
    cited = {c["url"] for c in citations}

    code, out = run(["fetch", "--study", str(own_study)], capsys)
    assert code == 0, out
    assert out["fetched"] == len(cited) and out["outcomes"] == {"ok": len(cited)}
    assert out["dated"] == len(cited)
    metas = rows(own_study / "data" / "page_meta.jsonl")
    assert {m["url"] for m in metas} == cited
    hosts = {httpx.URL(u).host for u in cited}
    assert {r.url.host for r in web.requests} == hosts  # only cited hosts were contacted
    assert {str(r.url) for r in web.requests if r.url.path != "/robots.txt"} <= cited
    log = fetch_pkg.FetchLog(own_study / "data" / "fetch_log.jsonl")
    assert audit(log) == []  # the gate-8 politeness audit passes on this log
    assert {r["user_agent"] for r in log.rows()} == {
        "citewatch/0.1.0 (+https://github.com/me/de-study)"
    }

    code, out = run(["score", "--study", str(own_study)], capsys)
    assert code == 0, out
    assert out["runs"] == [1]
    summary_path = own_study / "results" / "summary.json"
    summary = StudySummary.model_validate_json(summary_path.read_text(encoding="utf-8"))
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    text = json.dumps(raw)
    for intent in INTENTS:
        assert f'"{intent}"' in text, intent
    assert "nhs_services" not in text and "symptoms" not in text  # nothing from the flagship
    assert MODEL in text and "claude" not in text.lower()
    assert list(summary.runs) == [1]

    code, out = run(["report", "--study", str(own_study)], capsys)
    assert code == 0, out
    dashboard = Path(out["dashboard"])
    assert dashboard == own_study / "results" / "site" / "index.html"
    html = dashboard.read_text(encoding="utf-8")
    assert "Berlin, DE" in html and "de-study" in html

    assert len(provider.requests) == 3  # nothing was asked twice
