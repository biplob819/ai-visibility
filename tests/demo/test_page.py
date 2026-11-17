"""DEM-02, DEM-05 on the page itself (Streamlit AppTest, no browser, no network): live mode
asks for a passkey first, the registration code is checked and rate-limited, and a signed-in
question shows citations only, on the owner's keys or the visitor's own."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from citewatch.demo.guard import SpendGuard
from citewatch.demo.kv import KVError, SqliteKV
from citewatch.demo.live import ProviderKeys
from citewatch.demo.passkeys import STORE_DOWN, make_code_hash
from harness_lib import ROOT
from tests.demo.authenticator import SoftAuthenticator
from tests.demo.test_live import KEY_A, KEY_O, fake_runners, with_prose
from tests.runners.helpers import FakeAnthropic, FakeOpenAI, claude_raw, openai_raw

CODE = "481516234200"
OWNER_A = "-".join(["owner", "anthropic", "key", "c0ffee"])
OWNER_O = "-".join(["owner", "openai", "key", "decaf0"])


@pytest.fixture
def secrets(tmp_path) -> dict[str, str]:
    h, s = make_code_hash(CODE)
    return {
        "CITEWATCH_DEMO_CODE_HASH": h,
        "CITEWATCH_DEMO_CODE_SALT": s,
        "CITEWATCH_DEMO_RP_ID": "localhost",
        "CITEWATCH_DEMO_ORIGIN": "http://localhost:8501",
        "CITEWATCH_DEMO_LOCAL_STORE": str(tmp_path / "demo.sqlite"),
    }


@pytest.fixture
def given_keys(monkeypatch) -> list[ProviderKeys]:
    """Replace the SDK runners with fakes; record which keys the page handed over."""
    seen: list[ProviderKeys] = []

    def fake_make_runners(keys: ProviderKeys, models: Any) -> dict[str, Any]:
        seen.append(keys)
        return fake_runners(*[m for m in models if keys.for_provider(_provider(m))])

    monkeypatch.setattr("citewatch.demo.live.make_runners", fake_make_runners)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return seen


def _provider(model: str) -> str:
    return "anthropic" if model.startswith("claude") else "openai"


def app(secrets: dict[str, str]) -> AppTest:
    import streamlit as st

    st.cache_resource.clear()  # the store client is cached per process; each test has its own
    at = AppTest.from_file(str(ROOT / "demo" / "app.py"), default_timeout=120)
    for k, v in secrets.items():
        at.secrets[k] = v
    return at


def _live_markdown(at: AppTest) -> str:
    return "".join(m.value for m in at.markdown if "cw-live" in m.value)


@pytest.mark.safety
def test_live_tab_asks_for_a_passkey_before_anything(secrets, given_keys):
    at = app(secrets)
    at.run()
    assert not at.exception
    assert [s.value for s in at.subheader] == ["Sign in with your passkey"]
    assert not at.text_area  # no question box until signed in
    options = json.loads(at.session_state["pending_sign_in"][0])
    assert options["rpId"] == "localhost" and options["userVerification"] == "required"


@pytest.mark.safety
def test_page_registration_code_is_checked_and_rate_limited(secrets, given_keys):
    at = app(secrets)
    at.run()
    code_box = next(t for t in at.text_input if t.label == "Registration code")
    for _ in range(3):
        code_box.input("111111111111")
        at.button[0].click().run()
        assert any("not right" in e.value for e in at.error)
        code_box = next(t for t in at.text_input if t.label == "Registration code")
    code_box.input(CODE)
    at.button[0].click().run()
    assert any("Too many" in e.value for e in at.error)
    assert "grant" not in at.session_state


def test_page_right_code_starts_a_passkey_registration(secrets, given_keys):
    at = app(secrets)
    at.run()
    next(t for t in at.text_input if t.label == "Registration code").input(CODE)
    at.button[0].click().run()
    assert not at.exception and "grant" in at.session_state
    options = json.loads(at.session_state["pending_register"][0])
    assert options["rp"]["id"] == "localhost"
    assert options["authenticatorSelection"]["residentKey"] == "required"


def _ask(at: AppTest, question: str, own: tuple[str, str] | None) -> None:
    at.session_state["passkey_id"] = "credential-1"
    at.run()
    if own:
        at.radio[0].set_value("My own API keys").run()
        boxes = {t.label: t for t in at.text_input}
        boxes["Anthropic API key"].input(own[0])
        boxes["OpenAI API key"].input(own[1])
    at.text_area[0].input(question)
    next(b for b in at.button if b.label.startswith("Ask")).click().run()


@pytest.mark.safety
def test_page_live_question_on_own_keys_shows_citations_only(secrets, given_keys, caplog):
    caplog.set_level(logging.DEBUG)
    at = app(secrets)
    _ask(at, "QUESTION-SENTINEL how much is a prescription?", (KEY_A, KEY_O))
    assert not at.exception
    assert given_keys[-1] == ProviderKeys(KEY_A, KEY_O)  # the visitor's keys, not the owner's
    html = _live_markdown(at)
    assert "<ol class='cw-cites'>" in html and "nhs.uk" in html
    page = "".join(m.value for m in at.markdown)
    assert "PROSE-SENTINEL" not in page
    assert "QUESTION-SENTINEL" not in caplog.text
    db = (ROOT / secrets["CITEWATCH_DEMO_LOCAL_STORE"]).read_bytes()
    for key in (KEY_A, KEY_O):
        assert key not in caplog.text and key.encode() not in db and key not in page
    g = SpendGuard(SqliteKV(ROOT / secrets["CITEWATCH_DEMO_LOCAL_STORE"]))
    assert g.spent_today() == 0  # the owner's budget is untouched


@pytest.mark.safety
def test_page_live_question_on_owner_keys_counts_toward_the_daily_cap(secrets, given_keys):
    at = app({**secrets, "ANTHROPIC_API_KEY": OWNER_A})
    _ask(at, "How much is a prescription?", None)
    assert not at.exception
    assert given_keys[-1].anthropic == OWNER_A and given_keys[-1].openai == ""
    html = _live_markdown(at)
    assert "No openai key given." in html and "PROSE-SENTINEL" not in html
    g = SpendGuard(SqliteKV(ROOT / secrets["CITEWATCH_DEMO_LOCAL_STORE"]))
    assert g.spent_today() > 0


class FakeWidget:
    """Stands in for the components-v2 passkey element: records what the page mounts and
    replies, once, as the browser would after the visitor's click."""

    def __init__(self) -> None:
        self.mounted: dict[str, dict[str, str]] = {}
        self.replies: dict[str, Any] = {}

    def component(self, name: str, **kwargs: Any) -> Any:
        return self.mount

    def mount(self, *, key: str, data: dict[str, str], **kwargs: Any) -> dict[str, Any]:
        self.mounted[key] = data
        reply = self.replies.pop(key, None)
        return {"response": reply(data) if reply else None}


@pytest.mark.contract
def test_page_registers_a_passkey_then_signs_in_with_it(secrets, given_keys, monkeypatch):
    widget = FakeWidget()
    monkeypatch.setattr("streamlit.components.v2.component", widget.component)
    auth = SoftAuthenticator("localhost", "http://localhost:8501")
    at = app(secrets)
    at.run()
    assert widget.mounted["cw-sign-in"]["mode"] == "get"
    next(t for t in at.text_input if t.label == "Registration code").input(CODE)
    at.button[0].click().run()
    assert widget.mounted["cw-register"]["mode"] == "create"

    def created(data: dict[str, str]) -> str:
        return json.dumps({"nonce": data["nonce"], "credential": auth.create(data["options"])})

    widget.replies["cw-register"] = created
    at.run()
    assert not at.exception
    assert at.session_state["passkey_id"] == auth.id
    assert at.text_area  # signed in: the question box is shown

    next(b for b in at.button if b.label == "Sign out").click().run()
    assert "passkey_id" not in at.session_state

    def signed(data: dict[str, str]) -> str:
        return json.dumps({"nonce": data["nonce"], "credential": auth.get(data["options"])})

    widget.replies["cw-sign-in"] = signed
    at.run()
    assert at.session_state["passkey_id"] == auth.id


def test_page_refuses_a_stranger_passkey_and_offers_a_fresh_challenge(
    secrets, given_keys, monkeypatch
):
    widget = FakeWidget()
    monkeypatch.setattr("streamlit.components.v2.component", widget.component)
    stranger = SoftAuthenticator("localhost", "http://localhost:8501")
    at = app(secrets)
    at.run()
    first = widget.mounted["cw-sign-in"]["nonce"]

    def signed(data: dict[str, str]) -> str:
        return json.dumps({"nonce": data["nonce"], "credential": stranger.get(data["options"])})

    widget.replies["cw-sign-in"] = signed
    at.run()
    assert "passkey_id" not in at.session_state
    assert any("not registered" in w.value for w in at.warning)
    assert widget.mounted["cw-sign-in"]["nonce"] != first  # the used challenge is gone


# --- the visitor's own keys never fall back to the owner's (DEM-05) -------------------------------


@pytest.fixture
def sdk_clients(monkeypatch) -> list[tuple[str, str]]:
    """Stand in for the provider SDK constructors (no network): record which provider got a
    client and the key it would use. Like the real SDKs, a missing api_key falls back to the
    environment variable, so a fall-back to the owner's key would show up here."""
    made: list[tuple[str, str]] = []

    def anthropic_client(*, api_key: str | None = None, **kw: Any) -> FakeAnthropic:
        made.append(("anthropic", api_key or os.environ.get("ANTHROPIC_API_KEY", "")))
        return FakeAnthropic([with_prose("claude-sonnet-5-5", claude_raw())])

    def openai_client(*, api_key: str | None = None, **kw: Any) -> FakeOpenAI:
        made.append(("openai", api_key or os.environ.get("OPENAI_API_KEY", "")))
        return FakeOpenAI([with_prose("gpt-6.1-sol", openai_raw())])

    monkeypatch.setattr("anthropic.Anthropic", anthropic_client)
    monkeypatch.setattr("openai.OpenAI", openai_client)
    return made


@pytest.mark.safety
@pytest.mark.parametrize(
    ("given", "own", "missing"),
    [("openai", ("", KEY_O), "anthropic"), ("anthropic", (KEY_A, ""), "openai")],
)
def test_page_own_keys_with_one_key_never_use_the_owner_key(
    secrets, sdk_clients, monkeypatch, caplog, given, own, missing
):
    """The owner's keys are set (secrets and environment); the visitor picks their own keys
    and gives only one. The other model reports the missing key; the owner's key reaches no
    provider client, and the owner's daily budget is untouched."""
    caplog.set_level(logging.DEBUG)
    owner = {"ANTHROPIC_API_KEY": OWNER_A, "OPENAI_API_KEY": OWNER_O}
    for name, value in owner.items():
        monkeypatch.setenv(name, value)
    at = app({**secrets, **owner})
    _ask(at, "How much is a prescription?", own)
    assert not at.exception
    html = _live_markdown(at)
    assert f"No {missing} key given." in html
    assert "<ol class='cw-cites'>" in html  # the given key's model still answered
    assert sdk_clients == [(given, KEY_A if given == "anthropic" else KEY_O)]
    page = "".join(m.value for m in at.markdown)
    for key in (OWNER_A, OWNER_O):
        assert key not in caplog.text and key not in page
    g = SpendGuard(SqliteKV(ROOT / secrets["CITEWATCH_DEMO_LOCAL_STORE"]))
    assert g.spent_today() == 0


# --- failures never show a traceback ------------------------------------------------------------


@pytest.mark.safety
def test_page_store_failure_during_sign_in_is_a_message_not_a_traceback(
    secrets, given_keys, monkeypatch
):
    widget = FakeWidget()
    monkeypatch.setattr("streamlit.components.v2.component", widget.component)
    auth = SoftAuthenticator("localhost", "http://localhost:8501")
    at = app(secrets)
    at.run()
    next(t for t in at.text_input if t.label == "Registration code").input(CODE)
    at.button[0].click().run()
    widget.replies["cw-register"] = lambda d: json.dumps(
        {"nonce": d["nonce"], "credential": auth.create(d["options"])}
    )
    at.run()
    next(b for b in at.button if b.label == "Sign out").click().run()

    def down(*a: Any, **k: Any) -> Any:
        raise KVError("https://secret-kv.example token=abc")

    monkeypatch.setattr(SqliteKV, "hget", down)
    widget.replies["cw-sign-in"] = lambda d: json.dumps(
        {"nonce": d["nonce"], "credential": auth.get(d["options"])}
    )
    at.run()
    assert not at.exception
    assert "passkey_id" not in at.session_state
    assert [w.value for w in at.warning] == [STORE_DOWN]


@pytest.mark.safety
def test_page_misconfigured_origin_is_a_message_not_a_traceback(secrets, given_keys):
    at = app({**secrets, "CITEWATCH_DEMO_ORIGIN": "http://localhost.evil.example"})
    at.run()
    assert not at.exception
    assert any("not configured correctly" in i.value for i in at.info)
    assert all("evil" not in i.value for i in at.info)


def test_page_hides_error_details():
    import streamlit.config

    at = AppTest.from_file(str(ROOT / "demo" / "app.py"), default_timeout=120)
    at.run()
    assert streamlit.config.get_option("client.showErrorDetails") == "none"
