"""OSS-05 (D-25): the politeness floor cannot be lowered by study.yaml, a CLI flag or an
environment variable. The floor is: robots.txt always obeyed, at most 1 request per second
per host, at most 8 requests in flight, and at most 3 requests per page (one try and two
retries), with a user agent naming citewatch and a contact. Each test tries one route."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import typer
import yaml

import citewatch
import fetch_audit
from citewatch import cli
from citewatch import fetch as fetch_pkg
from citewatch.fetch import client as client_mod
from citewatch.fetch import rate as rate_mod
from citewatch.schemas import ConfigError, StudyConfig, load_study_config
from harness_lib import ROOT

from .web import FakeWeb, VClock

pytestmark = pytest.mark.polite

FLOOR = {"INTERVAL_S": 1.0, "MAX_IN_FLIGHT": 8, "MAX_RETRIES": 2}
LOOSENING_KEYS = {
    "rate_limit": 100,
    "requests_per_second": 100,
    "interval_s": 0,
    "min_interval": 0.01,
    "delay": 0,
    "obey_robots": False,
    "ignore_robots": True,
    "robots": "ignore",
    "max_in_flight": 512,
    "concurrency": 512,
    "max_retries": 50,
    "retries": 50,
    "politeness": {"interval_s": 0, "robots": False},
    "fetch": {"rate": 100, "ignore_robots": True},
}
LOOSENING_FLAGS = [
    ["--rate", "100"],
    ["--interval", "0"],
    ["--delay", "0"],
    ["--ignore-robots"],
    ["--no-robots"],
    ["--max-in-flight", "512"],
    ["--concurrency", "512"],
    ["--workers", "512"],
    ["--retries", "50"],
    ["--max-retries", "50"],
    ["--user-agent", "Mozilla/5.0"],
]
LOOSENING_ENV = {
    "CITEWATCH_RATE": "100",
    "CITEWATCH_INTERVAL_S": "0",
    "CITEWATCH_INTERVAL": "0",
    "CITEWATCH_DELAY": "0",
    "CITEWATCH_IGNORE_ROBOTS": "1",
    "CITEWATCH_OBEY_ROBOTS": "0",
    "CITEWATCH_ROBOTS": "ignore",
    "CITEWATCH_MAX_IN_FLIGHT": "512",
    "CITEWATCH_CONCURRENCY": "512",
    "CITEWATCH_MAX_RETRIES": "50",
    "CITEWATCH_RETRIES": "50",
    "CITEWATCH_USER_AGENT": "Mozilla/5.0",
    "HTTP_PROXY": "http://127.0.0.1:9",
    "HTTPS_PROXY": "http://127.0.0.1:9",
    "ALL_PROXY": "http://127.0.0.1:9",
}
# every environment variable citewatch itself reads, anywhere in the package
ALLOWED_ENV = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CITEWATCH_BODY_CACHE"}


# -- study.yaml ---------------------------------------------------------------------------


def test_the_floor_constants_are_what_d25_says():
    got = (rate_mod.INTERVAL_S, rate_mod.MAX_IN_FLIGHT, client_mod.MAX_RETRIES)
    assert got == (FLOOR["INTERVAL_S"], FLOOR["MAX_IN_FLIGHT"], FLOOR["MAX_RETRIES"])
    attempts = fetch_audit.MAX_ATTEMPTS  # the 3-requests-per-page rule the audit enforces
    assert attempts == FLOOR["MAX_RETRIES"] + 1 == 3


@pytest.mark.parametrize(("key", "value"), sorted(LOOSENING_KEYS.items()))
def test_study_yaml_cannot_carry_a_politeness_setting(tmp_path, key, value):
    data = yaml.safe_load((ROOT / "studies" / "uk-health" / "study.yaml").read_text("utf-8"))
    data[key] = value
    p = tmp_path / "study.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match=rf"{key}: Extra inputs are not permitted"):
        load_study_config(p)


def test_no_study_field_is_about_fetch_politeness():
    words = ("rate", "robot", "retr", "flight", "concurr", "interval", "delay", "politeness")
    assert [f for f in StudyConfig.model_fields if any(w in f for w in words)] == []


@pytest.mark.parametrize(
    "agent",
    [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "citewatch/0.1.0",  # no contact
        "citewatch/0.1.0 (+https://example.org/x)",  # a placeholder contact
    ],
)
def test_the_user_agent_cannot_hide_the_tool_or_the_contact(tmp_path, agent):
    data = yaml.safe_load((ROOT / "studies" / "uk-health" / "study.yaml").read_text("utf-8"))
    data["user_agent"] = agent
    p = tmp_path / "study.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="user_agent"):
        load_study_config(p)


# -- CLI flags ----------------------------------------------------------------------------


def test_fetch_takes_no_politeness_option():
    click_app = typer.main.get_command(cli.app)
    fetch = click_app.commands["fetch"]  # type: ignore[attr-defined]
    assert {o for p in fetch.params for o in p.opts} == {"--dry-run", "--study", "--json"}
    assert {o for p in click_app.params for o in p.opts} == {"--version"}


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert cli.main(["init", "s", "--contact", "https://github.com/me/study"]) == 0
    s = tmp_path / "s"
    urls = [
        "https://polite.test/a",
        "https://polite.test/b",
        "https://polite.test/private/c",
        "https://polite.test/flaky",
    ]
    rows = [
        {
            "run": 1,
            "question_id": "q-001",
            "model": "claude-sonnet-5-5",
            "url_raw": u,
            "url": u,
            "host": "polite.test",
            "publisher": "polite.test",
            "answer_span": "Some answer text.",
            "ordinal": i,
        }
        for i, u in enumerate(urls, 1)
    ]
    (s / "data").mkdir()
    (s / "data" / "citations.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    return s


@pytest.mark.parametrize("flag", LOOSENING_FLAGS, ids=lambda f: f[0])
def test_cli_flags_cannot_loosen_the_floor(study, capsys, flag):
    capsys.readouterr()
    for command in (["fetch"], ["fetch", "--dry-run"]):
        assert cli.main([*command, *flag, "--study", str(study)]) == 2
        assert "No such option" in capsys.readouterr().err
    assert not (study / "data" / "fetch_log.jsonl").exists()  # nothing was requested


# -- environment --------------------------------------------------------------------------


def _env_reads(tree: ast.AST) -> list[str | None]:
    """Names read from os.environ / os.getenv in a module: a literal name, or None."""
    found: list[str | None] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            found.append(None)
        if isinstance(node, ast.Call):
            f = node.func
            on_environ = isinstance(f, ast.Attribute) and (
                getattr(f.value, "attr", "") == "environ" and f.attr == "get"
            )
            reads = on_environ or (isinstance(f, ast.Attribute) and f.attr == "getenv")
            if reads and node.args and isinstance(node.args[0], ast.Constant):
                found.append(str(node.args[0].value))
    return found


def test_the_package_reads_only_key_and_cache_variables():
    """Static: no module reads a politeness variable. env.py reads the provider key names
    from its own table; the fetcher reads only where to cache support-sample text."""
    src = ROOT / "src" / "citewatch"
    readers: dict[str, list[str | None]] = {}
    for path in sorted(src.rglob("*.py")):
        reads = _env_reads(ast.parse(path.read_text(encoding="utf-8")))
        if reads:
            readers[path.relative_to(src).as_posix()] = reads
    assert set(readers) == {"env.py", "fetch/pages.py"}, readers
    assert {r for r in readers["fetch/pages.py"] if r} == {"CITEWATCH_BODY_CACHE"}
    from citewatch.env import PROVIDER_KEYS

    assert set(PROVIDER_KEYS.values()) | {"CITEWATCH_BODY_CACHE"} == ALLOWED_ENV


def test_environment_variables_do_not_change_the_floor_constants():
    """A fresh interpreter with every loosening variable set imports the same floor."""
    code = (
        "import json\n"
        "from citewatch.fetch import rate, client\n"
        "from citewatch.fetch.rate import HostLimiter\n"
        "h = HostLimiter()\n"
        "print(json.dumps([rate.INTERVAL_S, rate.MAX_IN_FLIGHT, client.MAX_RETRIES,"
        " h.interval, h._slots._value]))\n"
    )
    env = {**os.environ, **LOOSENING_ENV}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(out) == [1.0, 8, 2, 1.0, 8]


def test_environment_variables_cannot_loosen_a_real_fetch(study, capsys, monkeypatch):
    """End to end through `citewatch fetch` with every loosening variable set: only the
    transport and the clock are replaced, never the limiter's interval or slots, and the
    gate-8 audit passes on the log it writes."""
    for k, v in LOOSENING_ENV.items():
        monkeypatch.setenv(k, v)
    clock = VClock()
    web = FakeWeb(
        {
            "https://polite.test/robots.txt": httpx.Response(
                200, text="User-agent: *\nDisallow: /private\n"
            ),
            "https://polite.test/flaky": httpx.Response(503),
        }
    )
    limiters: list[rate_mod.HostLimiter] = []
    real_limiter, real_client = rate_mod.HostLimiter, fetch_pkg.PoliteClient

    def limiter(*args, **kw):
        assert not args and set(kw) <= {"clock", "sleep", "wall"}, (args, kw)
        lim = real_limiter(clock=clock.now, sleep=clock.sleep, wall=clock.wall)
        limiters.append(lim)
        return lim

    def polite_client(ua, log, **kw):
        assert "limiter" not in kw  # the command builds no looser limiter of its own
        return real_client(
            ua, log, transport=httpx.MockTransport(web.handler), sleep=clock.sleep, **kw
        )

    monkeypatch.setattr(client_mod, "HostLimiter", limiter)
    monkeypatch.setattr(fetch_pkg, "PoliteClient", polite_client)
    capsys.readouterr()
    cli.main(["fetch", "--study", str(study), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["outcomes"]["robots_disallowed"] == 1
    (lim,) = limiters
    assert lim.interval == 1.0 and lim._slots._value == 8 and lim.max_live <= 8
    urls = web.urls()
    assert not any("/private/" in u for u in urls)  # robots obeyed
    assert urls.count("https://polite.test/flaky") == 3  # one try and two retries
    agents = {r.headers["user-agent"] for r in web.requests}
    assert agents == {f"citewatch/{citewatch.__version__} (+https://github.com/me/study)"}
    log = study / "data" / "fetch_log.jsonl"
    assert fetch_audit.audit_paths([log]) == []  # 1 s per host, robots, 3 per page, one UA
    rows = [json.loads(x) for x in log.read_text("utf-8").splitlines() if x]
    sent = [r for r in rows if r["outcome"] != "robots_disallowed"]
    assert len(sent) == len(urls)  # every request made was logged


def test_the_fetcher_ignores_proxy_variables():
    """trust_env is off, so HTTP(S)_PROXY cannot route requests around the log."""
    src = Path(client_mod.__file__).read_text(encoding="utf-8")
    assert src.count("trust_env=False") >= 2
