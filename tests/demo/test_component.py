"""DEM-02: the browser half of passkey sign-in (a Streamlit components-v2 element). The JS is
checked for the WebAuthn calls and the JSON shape py_webauthn parses; the Python side for
binding each response to its own ceremony."""

from __future__ import annotations

import json

import pytest

from citewatch.demo.component import JS, component_data, parse_response
from citewatch.demo.kv import SqliteKV
from citewatch.demo.passkeys import CredentialStore, Passkeys
from tests.demo.authenticator import SoftAuthenticator


def test_js_runs_both_webauthn_calls_on_a_click_and_returns_a_trigger_value():
    assert "navigator.credentials.create" in JS and "navigator.credentials.get" in JS
    assert "button.onclick" in JS  # a user gesture, which Safari requires
    assert "setTriggerValue('response'" in JS
    assert "export default function" in JS  # the components-v2 entry point


def test_js_returns_the_webauthn_json_fields_py_webauthn_reads():
    for name in (
        "rawId",
        "clientDataJSON",
        "attestationObject",
        "authenticatorData",
        "signature",
        "userHandle",
        "clientExtensionResults",
    ):
        assert name in JS, name


@pytest.mark.safety
def test_js_never_writes_html_from_data():
    assert "innerHTML" not in JS and "outerHTML" not in JS and "eval(" not in JS


def test_component_data_validates_mode_and_options():
    assert component_data("get", "{}", "n1", "Sign in")["mode"] == "get"
    with pytest.raises(ValueError):
        component_data("steal", "{}", "n1", "x")
    with pytest.raises(ValueError):
        component_data("get", "not json", "n1", "x")


def test_parse_response_binds_the_answer_to_its_ceremony():
    cred = {"id": "abc", "rawId": "abc", "response": {}}
    good = json.dumps({"nonce": "n1", "credential": cred})
    assert parse_response(good, "n1") == (cred, None)
    assert parse_response(good, "n2") == (None, None)  # a stale value from another ceremony
    assert parse_response(None, "n1") == (None, None)
    assert parse_response("{", "n1") == (None, "unreadable")
    err = json.dumps({"nonce": "n1", "error": "NotAllowedError"})
    assert parse_response(err, "n1") == (None, "NotAllowedError")


def test_a_browser_shaped_response_round_trips_to_verification(tmp_path):
    """What the component sends (JSON-encoded, wrapped with the nonce) verifies server-side."""
    pk = Passkeys("localhost", "http://localhost:8501", CredentialStore(SqliteKV(tmp_path / "k")))
    auth = SoftAuthenticator("localhost", "http://localhost:8501")
    from citewatch.demo.passkeys import RegistrationGrant

    options, pending = pk.registration_options(RegistrationGrant("s", 1e12), "s")
    sent = json.dumps({"nonce": "n", "credential": auth.create(options)})
    cred, err = parse_response(sent, "n")
    assert err is None and cred is not None
    assert pk.finish_registration(pending, cred).credential_id == auth.id
