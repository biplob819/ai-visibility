"""DEM-02 (passkey sign-in, OWNER D-58) and D-59 (registration code): the code hash and its
rate-limited check, and the WebAuthn ceremonies verified by py_webauthn against a software
authenticator that signs like a real one."""

from __future__ import annotations

import hmac
import json

import pytest

from citewatch.demo import make_code_hash as cli
from citewatch.demo.kv import SqliteKV
from citewatch.demo.passkeys import (
    HASH_ITERATIONS,
    AuthRefused,
    CredentialStore,
    Passkeys,
    RegistrationGate,
    check_code,
    make_code_hash,
)
from tests.demo.authenticator import SoftAuthenticator

RP, ORIGIN = "citewatch.streamlit.app", "https://citewatch.streamlit.app"
CODE = "48151623"


class Clock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def kv(tmp_path):
    return SqliteKV(tmp_path / "demo.sqlite")


@pytest.fixture
def gate(kv):
    h, salt = make_code_hash(CODE, iterations=1_000)
    return RegistrationGate(kv, h, salt, clock=Clock())


@pytest.fixture
def pk(kv):
    return Passkeys(RP, ORIGIN, CredentialStore(kv), clock=Clock())


def _register(pk: Passkeys, gate: RegistrationGate, auth: SoftAuthenticator, session="s1"):
    grant = gate.check(session, CODE)
    options, pending = pk.registration_options(grant, session)
    return pk.finish_registration(pending, auth.create(options))


# --- the registration code (D-59) ---------------------------------------------------------------


def test_code_hash_is_salted_pbkdf2_and_never_contains_the_code():
    h1, s1 = make_code_hash(CODE)
    h2, s2 = make_code_hash(CODE)
    assert h1.startswith(f"pbkdf2_sha256${HASH_ITERATIONS}$")
    assert s1 != s2 and h1 != h2  # a fresh salt each time
    assert CODE not in h1 + s1
    assert check_code(CODE, h1, s1) and not check_code("48151624", h1, s1)


@pytest.mark.parametrize("bad", ["1234567", "abcdefgh", "1234 5678", "١٢٣٤٥٦٧٨", "9" * 33])
def test_code_must_be_8_to_32_ascii_digits(bad):
    with pytest.raises(ValueError):
        make_code_hash(bad)


def test_check_code_uses_a_constant_time_compare(monkeypatch):
    seen = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr("citewatch.demo.passkeys.hmac.compare_digest", spy)
    h, s = make_code_hash(CODE, iterations=1_000)
    assert check_code(CODE, h, s)
    assert seen and all(isinstance(a, bytes) for a, _ in seen)


@pytest.mark.parametrize("stored", ["", "md5$1$00", "pbkdf2_sha256$x$00", "pbkdf2_sha256$1$zz"])
def test_check_code_rejects_malformed_stored_hashes(stored):
    assert not check_code(CODE, stored, "00ff")


@pytest.mark.safety
def test_registration_rejects_a_wrong_code(gate):
    with pytest.raises(AuthRefused, match="not right"):
        gate.check("s1", "11111111")


@pytest.mark.safety
def test_registration_rate_limits_per_session_even_for_the_right_code(gate):
    for _ in range(gate.per_session):
        with pytest.raises(AuthRefused, match="not right"):
            gate.check("s1", "11111111")
    with pytest.raises(AuthRefused, match="Too many"):
        gate.check("s1", CODE)  # locked out: the right code learns nothing either
    assert gate.check("s2", CODE).session == "s2"  # another session is unaffected


@pytest.mark.safety
def test_registration_rate_limits_across_sessions(gate):
    for i in range(gate.overall):
        with pytest.raises(AuthRefused, match="not right"):
            gate.check(f"s{i}", "11111111")
    with pytest.raises(AuthRefused, match="Too many"):
        gate.check("fresh", CODE)


def test_registration_lockout_ends_after_the_window(kv):
    clock = Clock()
    h, s = make_code_hash(CODE, iterations=1_000)
    gate = RegistrationGate(kv, h, s, clock=clock)
    for _ in range(gate.per_session):
        with pytest.raises(AuthRefused):
            gate.check("s1", "11111111")
    with pytest.raises(AuthRefused, match="Too many"):
        gate.check("s1", CODE)
    clock.t += gate.window_s
    assert gate.check("s1", CODE)


def test_registration_refuses_readably_when_the_store_is_down(gate, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("https://secret-kv.example token=abc")

    monkeypatch.setattr(gate.kv, "incr", boom)
    with pytest.raises(AuthRefused) as exc:
        gate.check("s1", CODE)
    assert "secret-kv" not in exc.value.reason and "token" not in exc.value.reason


@pytest.mark.safety
def test_make_code_hash_reads_without_echo_and_never_prints_the_code():
    prompts, out = [], []

    def read(prompt: str) -> str:  # stands in for getpass.getpass (no echo)
        prompts.append(prompt)
        return CODE

    assert cli.main(read=read, write=out.append) == 0
    assert len(prompts) == 2  # asked twice
    text = "\n".join(out)
    assert CODE not in text
    lines = {ln.split(" = ")[0]: ln.split(" = ")[1].strip('"') for ln in out if " = " in ln}
    assert check_code(CODE, lines["CITEWATCH_DEMO_CODE_HASH"], lines["CITEWATCH_DEMO_CODE_SALT"])


def test_make_code_hash_cli_uses_getpass_and_rejects_bad_input(monkeypatch):
    import getpass

    assert cli.main.__defaults__ is not None and cli.main.__defaults__[0] is getpass.getpass
    out: list[str] = []
    assert cli.main(read=lambda _: "1234", write=out.append) == 2
    answers = iter([CODE, "99999999"])
    assert cli.main(read=lambda _: next(answers), write=out.append) == 2
    assert CODE not in "\n".join(out)


# --- WebAuthn ceremonies (py_webauthn) ---------------------------------------------------------


@pytest.mark.contract
def test_register_then_sign_in_with_a_passkey(pk, gate):
    auth = SoftAuthenticator(RP, ORIGIN)
    cred = _register(pk, gate, auth)
    assert cred.credential_id == auth.id and pk.store.count() == 1

    options, pending = pk.authentication_options()
    opts = json.loads(options)
    assert opts["rpId"] == RP and opts["userVerification"] == "required"
    assert opts.get("allowCredentials", []) == []  # discoverable: no user name needed
    signed = pk.finish_authentication(pending, auth.get(options))
    assert signed.credential_id == auth.id and signed.sign_count == 1
    assert pk.store.get(auth.id).sign_count == 1  # the counter is kept for clone detection


def test_registration_options_require_resident_key_and_user_verification(pk, gate):
    options, pending = pk.registration_options(gate.check("s1", CODE), "s1")
    o = json.loads(options)
    assert o["rp"]["id"] == RP
    assert o["authenticatorSelection"]["residentKey"] == "required"
    assert o["authenticatorSelection"]["userVerification"] == "required"
    assert o["attestation"] == "none"
    assert pending.kind == "register" and len(pending.challenge) >= 16


def test_stored_credential_holds_no_personal_data(pk, gate, kv):
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)
    raw = json.loads(kv.hget("passkeys", auth.id))
    assert set(raw) == {"public_key", "sign_count", "added"}


def test_registration_options_need_a_grant_for_this_session(pk, gate):
    grant = gate.check("s1", CODE)
    with pytest.raises(AuthRefused):
        pk.registration_options(grant, "someone-else")


def test_expired_grant_is_refused(kv):
    clock = Clock()
    h, s = make_code_hash(CODE, iterations=1_000)
    gate = RegistrationGate(kv, h, s, clock=clock)
    pk = Passkeys(RP, ORIGIN, CredentialStore(kv), clock=clock)
    grant = gate.check("s1", CODE)
    clock.t += 301
    with pytest.raises(AuthRefused, match="again"):
        pk.registration_options(grant, "s1")


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"origin": "https://evil.example"}, "wrong origin"),
        ({"rp_id": "evil.example"}, "wrong RP ID"),
        ({"user_verified": False}, "no user verification"),
    ],
)
def test_registration_rejects_bad_responses(pk, gate, kwargs, why):
    auth = SoftAuthenticator(RP, ORIGIN)
    options, pending = pk.registration_options(gate.check("s1", CODE), "s1")
    with pytest.raises(AuthRefused, match="could not be verified"):
        pk.finish_registration(pending, auth.create(options, **kwargs))
    assert pk.store.count() == 0, why


def test_registration_rejects_a_response_to_another_challenge(pk, gate):
    auth = SoftAuthenticator(RP, ORIGIN)
    first, _ = pk.registration_options(gate.check("s1", CODE), "s1")
    _, pending = pk.registration_options(gate.check("s1", CODE), "s1")
    with pytest.raises(AuthRefused):
        pk.finish_registration(pending, auth.create(first))


def test_sign_in_rejects_unknown_wrong_origin_replay_and_expired(kv, gate):
    clock = Clock()
    pk = Passkeys(RP, ORIGIN, CredentialStore(kv), clock=clock)
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)

    stranger = SoftAuthenticator(RP, ORIGIN)
    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused, match="not registered"):
        pk.finish_authentication(pending, stranger.get(options))

    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused, match="could not be verified"):
        pk.finish_authentication(pending, auth.get(options, origin="https://evil.example"))

    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused, match="could not be verified"):
        pk.finish_authentication(pending, auth.get(options, user_verified=False))

    old_options, _ = pk.authentication_options()
    _, pending = pk.authentication_options()
    with pytest.raises(AuthRefused, match="could not be verified"):
        pk.finish_authentication(pending, auth.get(old_options))  # another challenge

    options, pending = pk.authentication_options()
    clock.t += 301
    with pytest.raises(AuthRefused, match="expired"):
        pk.finish_authentication(pending, auth.get(options))


def test_sign_in_rejects_a_cloned_authenticator_counter(pk, gate):
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)
    options, pending = pk.authentication_options()
    pk.finish_authentication(pending, auth.get(options, count=5))
    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused):
        pk.finish_authentication(pending, auth.get(options, count=3))


def test_a_registration_pending_cannot_finish_a_sign_in(pk, gate):
    auth = SoftAuthenticator(RP, ORIGIN)
    options, pending = pk.registration_options(gate.check("s1", CODE), "s1")
    with pytest.raises(AuthRefused, match="expired"):
        pk.finish_authentication(pending, auth.get(options))


def test_the_same_passkey_cannot_register_twice(pk, gate):
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)
    with pytest.raises(AuthRefused, match="already registered"):
        _register(pk, gate, auth, session="s2")


def test_passkeys_need_an_https_origin(kv):
    with pytest.raises(ValueError):
        Passkeys(RP, "http://citewatch.streamlit.app", CredentialStore(kv))
    assert Passkeys("localhost", "http://localhost:8501", CredentialStore(kv))
