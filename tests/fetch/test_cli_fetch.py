"""FET-05: `citewatch fetch` reads canonical citation URLs; `--dry-run` needs no keys."""

import json

import httpx
import pytest

from citewatch import cli
from citewatch import fetch as fetch_pkg

from .web import FakeWeb, VClock, audit


def cite(url, host, qid="q-001", n=1):
    pub = ".".join(host.split(".")[-2:])
    return json.dumps(
        {
            "run": 1,
            "question_id": qid,
            "model": "claude-sonnet-5-5",
            "url_raw": url,
            "url": url,
            "host": host,
            "publisher": pub,
            "answer_span": "Some answer text.",
            "ordinal": n,
        }
    )


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["init", "s", "--contact", "https://github.com/me/study"]) == 0
    s = tmp_path / "s"
    rows = [
        cite("https://www.nhs.uk/a", "www.nhs.uk"),
        cite("https://www.nhs.uk/b", "www.nhs.uk", n=2),
        cite("https://www.nhs.uk/a", "www.nhs.uk", qid="q-002"),
        cite("https://example.org/x", "example.org"),
    ]
    (s / "data").mkdir()
    (s / "data" / "citations.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return s


@pytest.mark.onboarding
def test_dry_run_lists_hosts_and_time_with_no_keys_and_no_requests(study, capsys, monkeypatch):
    def no_client(*a, **k):
        raise AssertionError("a dry run must not build a client")

    monkeypatch.setattr(fetch_pkg, "PoliteClient", no_client)
    capsys.readouterr()
    assert cli.main(["fetch", "--dry-run", "--study", str(study), "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["urls"] == 3 and plan["to_fetch"] == 3 and plan["hosts"] == 2
    assert plan["min_seconds"] == 3  # robots + 2 pages on www.nhs.uk, 1 s apart


def test_a_missing_citations_file_names_the_next_step(study, capsys):
    (study / "data" / "citations.jsonl").unlink()
    assert cli.main(["fetch", "--study", str(study)]) == 2
    assert "citewatch extract" in capsys.readouterr().out


def test_a_real_fetch_writes_the_log_and_resumes(study, capsys, monkeypatch):
    web = FakeWeb({"https://www.nhs.uk/b": httpx.Response(403)})
    clock = VClock()
    real = fetch_pkg.PoliteClient

    def fake_client(ua, log, **kw):
        lim = fetch_pkg.HostLimiter(clock=clock.now, sleep=clock.sleep, wall=clock.wall)
        return real(
            ua,
            log,
            transport=httpx.MockTransport(web.handler),
            limiter=lim,
            sleep=clock.sleep,
            **kw,
        )

    monkeypatch.setattr(fetch_pkg, "PoliteClient", fake_client)
    capsys.readouterr()
    assert cli.main(["fetch", "--study", str(study), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fetched"] == 3 and out["outcomes"] == {"ok": 2, "blocked": 1}
    log = fetch_pkg.FetchLog(study / "data" / "fetch_log.jsonl")
    assert audit(log) == []
    assert {r["user_agent"] for r in log.rows()} == {web.requests[0].headers["user-agent"]}
    n = len(web.requests)
    assert cli.main(["fetch", "--study", str(study), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cached"] == 0 and len(web.requests) == n
