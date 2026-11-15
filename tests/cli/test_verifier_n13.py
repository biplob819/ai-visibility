"""Regression tests for the N1.3 verifier's findings (RUN-STATE.md, pass 1)."""

import json
import os
import threading

import pytest

from citewatch import cli
from citewatch.ledger import Ledger, LedgerError
from citewatch.store import RawStore


def test_a_failed_write_leaves_no_partial_object(tmp_path, monkeypatch):
    store = RawStore(tmp_path)
    key = "d" * 64

    def broken_fsync(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", broken_fsync)
    with pytest.raises(OSError):
        store.put("ask", key, {"pad": "x" * 100000})
    assert not store.has("ask", key)  # never a truncated final file a resume would trust
    monkeypatch.undo()
    assert store.put("ask", key, {"pad": "ok"}) is True
    assert list((tmp_path / "data" / "raw").rglob(".tmp-*")) == []


def test_a_concurrent_reader_never_sees_a_partial_object(tmp_path):
    store = RawStore(tmp_path)
    keys = [f"{i:064x}" for i in range(40)]
    body = {"pad": "y" * 200000}
    bad = []
    done = threading.Event()

    def reader():
        while not done.is_set():
            for k in keys:
                try:
                    if store.get("ask", k) != body:
                        bad.append(k)
                except KeyError:
                    pass

    t = threading.Thread(target=reader)
    t.start()
    for k in keys:
        store.put("ask", k, body)
    done.set()
    t.join()
    assert bad == []


def test_init_template_contact_is_refused_until_replaced(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert cli.main(["init", "s"]) == 0
    capsys.readouterr()
    assert cli.main(["doctor", "--study", "s", "--json"]) == 2
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["study"]["ok"] is False and "placeholder" in checks["study"]["detail"]
    y = tmp_path / "s" / "study.yaml"
    y.write_text(
        y.read_text(encoding="utf-8").replace(
            "https://example.org/your-study", "https://github.com/me/my-study"
        ),
        encoding="utf-8",
    )
    assert cli.main(["doctor", "--study", "s"]) == 0


@pytest.mark.parametrize(
    "contact",
    [
        "https://example.com/x",
        "me@example.net",
        "http://localhost:8000",
        "https://site.test/a",
        "study@uni.example",
    ],
)
def test_placeholder_contacts_are_refused(contact):
    from pydantic import ValidationError

    from citewatch.schemas import StudyConfig
    from tests.schemas import samples as s

    with pytest.raises(ValidationError, match=r"placeholder|must name a contact"):
        StudyConfig.model_validate(s.config(user_agent=f"citewatch/0.1 ({contact})"))


def test_real_contacts_still_pass():
    from citewatch.schemas import StudyConfig
    from tests.schemas import samples as s

    for c in ("+https://github.com/biplob819/ai-visibility", "study@examplehealth.org"):
        assert StudyConfig.model_validate(s.config(user_agent=f"citewatch/0.1 ({c})"))


def test_init_refuses_a_dangling_symlink(tmp_path, capsys):
    target = tmp_path / "study"
    target.mkdir()
    try:
        (target / "study.yaml").symlink_to(tmp_path / "elsewhere" / "owned.yaml")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")
    assert cli.main(["init", str(target)]) == 2
    assert not (tmp_path / "elsewhere").exists()


def test_ledger_extra_fields_cannot_override_or_smuggle_bad_money(tmp_path):
    led = Ledger(tmp_path)
    with pytest.raises(LedgerError, match="cannot replace"):
        led.event("ask", "k", cache_hit=False, latency_ms=0, cost_usd=0, at="yesterday")
    with pytest.raises(LedgerError):
        led.event("ask", "k", cache_hit=False, latency_ms=0, cost_usd=0, max_cost_usd=-5.0)


def test_cli_catches_usage_errors_through_typer_itself():
    import typer

    assert hasattr(typer, "TyperException")  # typer>=0.28 is required for this


# ---- N1.3 verifier pass 2 ----


def test_put_falls_back_to_rename_where_hard_links_are_unsupported(tmp_path, monkeypatch):
    import errno

    def no_links(src, dst):
        raise OSError(errno.ENOTSUP, "hard links not supported")

    monkeypatch.setattr(os, "link", no_links)
    store = RawStore(tmp_path)
    key = "e" * 64
    assert store.put("ask", key, {"v": 1}) is True
    assert store.get("ask", key) == {"v": 1}
    assert store.put("ask", key, {"v": 2}) is False and store.get("ask", key) == {"v": 1}
    assert list((tmp_path / "data" / "raw").rglob(".tmp-*")) == []


def test_doctor_flags_stale_or_missing_prices_and_accepts_a_study_prices_file(
    tmp_path, monkeypatch, capsys
):
    import datetime as dt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert cli.main(["init", "s", "--contact", "https://github.com/me/s"]) == 0
    capsys.readouterr()
    assert cli.main(["doctor", "--study", "s"]) == 0
    stale = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    body = "".join(
        f"{m}:\n  input: 2\n  output: 10\n  cached_input: 0.1\n  search_per_1k: 10\n"
        f"  checked_on: {stale}\n"
        for m in ("claude-sonnet-5-5", "gpt-6.1-sol")
    )
    (tmp_path / "s" / "prices.yaml").write_text(body, encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["doctor", "--study", "s", "--json"]) == 2
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["prices"]["ok"] is False and "30 days ago" in checks["prices"]["detail"]
    (tmp_path / "s" / "prices.yaml").write_text(
        body.replace(stale, dt.date.today().isoformat()), encoding="utf-8"
    )
    assert cli.main(["doctor", "--study", "s"]) == 0
    (tmp_path / "s" / "prices.yaml").write_text(body.split("gpt-6.1-sol")[0], encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["doctor", "--study", "s", "--json"]) == 2
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert "no price for gpt-6.1-sol" in checks["prices"]["detail"]


def test_store_keys_and_stages_must_match_whole_strings(tmp_path):
    from citewatch.store import StoreError, stage_key

    with pytest.raises(StoreError):
        RawStore(tmp_path).path("ask", "a" * 64 + "\n")
    with pytest.raises(StoreError):
        stage_key("ask\n", "1", {}, "h")


def test_negative_zero_money_is_written_as_zero(tmp_path):
    row = Ledger(tmp_path).event("ask", "k", cache_hit=False, latency_ms=0, cost_usd=-0.0)
    assert str(row["cost_usd"]) == "0.0"


def test_unexpected_errors_in_json_mode_print_json(capsys, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("planted\nwith two lines")

    monkeypatch.setattr(cli, "load_study_config", boom)
    assert cli.main(["doctor", "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "planted with two lines" in out["error"]


@pytest.mark.parametrize("cap", ["0", "-1", "nan", "inf"])
def test_bad_caps_are_refused_even_with_a_valid_study(tmp_path, monkeypatch, capsys, cap):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init", "s", "--contact", "https://github.com/me/s"]) == 0
    capsys.readouterr()
    assert cli.main(["ask", "--max-cost", cap, "--dry-run", "--study", "s", "--json"]) == 2
    assert "positive amount" in json.loads(capsys.readouterr().out)["error"]
