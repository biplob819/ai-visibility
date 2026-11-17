"""DEM-03: aggregate-only logging (timestamp, mode, latency, cost; no question, no IP) and
secrets only from the host's secret store or the environment."""

from __future__ import annotations

import ast
import json
import logging
from datetime import UTC, datetime

import pytest

from citewatch.demo import settings as S
from citewatch.demo.kv import SqliteKV, UpstashKV
from citewatch.demo.logs import FIELDS, MODES, log_request
from harness_lib import ROOT

APP = ROOT / "demo" / "app.py"


@pytest.mark.safety
def test_log_record_has_exactly_the_allowed_fields(caplog):
    caplog.set_level(logging.INFO, logger="citewatch.demo")
    rec = log_request(
        "live-own-keys", 1234.6, 0.0812345, now=lambda: datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
    )
    assert tuple(sorted(rec)) == tuple(sorted(FIELDS)) == ("at", "cost_usd", "latency_ms", "mode")
    assert rec == {
        "at": "2026-11-17T09:00:00Z",
        "mode": "live-own-keys",
        "latency_ms": 1234,
        "cost_usd": 0.081235,
    }
    lines = [json.loads(r.getMessage()) for r in caplog.records]
    assert lines == [rec]


@pytest.mark.safety
def test_log_mode_is_a_closed_set_so_no_free_text_gets_in():
    assert {"lookup", "live-owner-keys", "live-own-keys"} == MODES
    with pytest.raises(ValueError):
        log_request("what is the NHS prescription charge?", 1, 0)


def test_log_cleans_bad_numbers():
    rec = log_request("lookup", -5, float("nan"))
    assert rec["latency_ms"] == 0 and rec["cost_usd"] == 0.0


@pytest.mark.safety
def test_other_log_calls_carry_only_an_exception_type_name():
    """Apart from `log_request`, a demo log call is a fixed message plus at most an
    exception's type name: never request text, a key or a provider's message."""
    seen = 0
    for path in [*(ROOT / "src" / "citewatch" / "demo").glob("*.py"), APP]:
        if path.name == "logs.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("info", "warning", "error", "debug", "exception")
                and ast.unparse(node.func.value) in ("LOG", "logger", "logging")
            ):
                continue
            where = f"{path.name}: {ast.unparse(node)}"
            seen += 1
            assert node.args and isinstance(node.args[0], ast.Constant), where
            for a in node.args[1:]:
                text = ast.unparse(a)
                assert text.startswith("type(") and text.endswith(").__name__"), where
    assert seen >= 5  # the walk really found the guard's and the page's warnings


# --- secrets ---------------------------------------------------------------------------------


FULL = {
    "CITEWATCH_DEMO_CODE_HASH": "pbkdf2_sha256$1000$00",
    "CITEWATCH_DEMO_CODE_SALT": "00",
    "CITEWATCH_DEMO_RP_ID": "citewatch.streamlit.app",
    "CITEWATCH_DEMO_ORIGIN": "https://citewatch.streamlit.app",
    "CITEWATCH_DEMO_KV_URL": "https://example-kv.upstash.io",
    "CITEWATCH_DEMO_KV_TOKEN": "kv-token-value",
}


@pytest.mark.safety
def test_live_mode_needs_every_required_secret_and_never_quotes_one():
    assert S.live_problem(FULL) is None
    for name in FULL:
        env = {k: v for k, v in FULL.items() if k != name}
        problem = S.live_problem(env)
        assert problem and not any(v in problem for v in FULL.values())
        assert S.missing(env) == [name]


def test_owner_keys_are_optional():
    assert not S.has_owner_keys(FULL)
    assert S.has_owner_keys({**FULL, "ANTHROPIC_API_KEY": "x"})


def test_store_is_the_hosted_kv_or_an_explicit_local_file(tmp_path):
    assert isinstance(S.make_kv(FULL), UpstashKV)
    local = {k: v for k, v in FULL.items() if not k.startswith("CITEWATCH_DEMO_KV")}
    assert S.missing(local) == ["CITEWATCH_DEMO_KV_URL", "CITEWATCH_DEMO_KV_TOKEN"]
    local[S.LOCAL_STORE] = str(tmp_path / "x.sqlite")
    assert S.missing(local) == [] and isinstance(S.make_kv(local), SqliteKV)
    with pytest.raises(ValueError):
        S.make_kv({})


@pytest.mark.safety
def test_app_reads_secrets_only_from_st_secrets_and_the_environment():
    src = APP.read_text(encoding="utf-8")
    assert "load_dotenv" not in src and ".env" not in src.replace("os.environ", "")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "secret_env"
    )
    body = ast.unparse(fn)
    assert "st.secrets" in body and "os.environ" in body
    # nowhere else in the page touches the environment
    assert src.count("os.environ") == body.count("os.environ")
    for name in S.ALL_SECRETS:  # no secret value is written into the page
        assert f'{name} = "' not in src
