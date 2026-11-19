"""DEM-02 (passkey sign-in, OWNER D-58) and D-59 (registration code): the code hash and its
rate-limited check, and the WebAuthn ceremonies verified by py_webauthn against a software
authenticator that signs like a real one."""

from __future__ import annotations

import hmac
import json

import pytest

from citewatch.demo import make_code_hash as cli
from citewatch.demo.kv import KVError, SqliteKV
from citewatch.demo.passkeys import (
    CODE_WINDOW_S,
    HASH_ITERATIONS,
    STORE_DOWN,
    AuthRefused,
    CredentialStore,
    Passkeys,
    RegistrationGate,
    check_code,
    exact_origin,
    make_code_hash,
)
from tests.demo.authenticator import SoftAuthenticator

RP, ORIGIN = "citewatch.streamlit.app", "https://citewatch.streamlit.app"
CODE = "481516234200"


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
    h, salt = make_code_hash(CODE)
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
    assert check_code(CODE, h1, s1) and not check_code("481516234201", h1, s1)


@pytest.mark.parametrize(
    "bad", ["48151623", "12345678901", "abcdefghijkl", "1234 5678 90", "١٢٣٤٥٦٧٨٩٠١٢", "9" * 33]
)
def test_code_must_be_12_to_32_ascii_digits(bad):
    with pytest.raises(ValueError):
        make_code_hash(bad)


def test_an_8_digit_code_no_longer_passes_even_against_its_own_hash():
    """The 12-digit floor is a check rule too, not only a rule for making the hash."""
    import hashlib

    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", b"48151623", salt, HASH_ITERATIONS).hex()
    assert not check_code("48151623", f"pbkdf2_sha256${HASH_ITERATIONS}${digest}", salt.hex())


def test_stored_hashes_below_600k_rounds_are_refused():
    import hashlib

    salt = b"0123456789abcdef"
    weak = hashlib.pbkdf2_hmac("sha256", CODE.encode(), salt, 1_000).hex()
    assert not check_code(CODE, f"pbkdf2_sha256$1000${weak}", salt.hex())
    with pytest.raises(ValueError, match="rounds"):
        make_code_hash(CODE, iterations=HASH_ITERATIONS - 1)


def test_check_code_uses_a_constant_time_compare(monkeypatch):
    seen = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr("citewatch.demo.passkeys.hmac.compare_digest", spy)
    h, s = make_code_hash(CODE)
    assert check_code(CODE, h, s)
    assert seen and all(isinstance(a, bytes) for a, _ in seen)


@pytest.mark.parametrize("stored", ["", "md5$1$00", "pbkdf2_sha256$x$00", "pbkdf2_sha256$1$zz"])
def test_check_code_rejects_malformed_stored_hashes(stored):
    assert not check_code(CODE, stored, "00ff")


@pytest.mark.safety
def test_registration_rejects_a_wrong_code(gate):
    with pytest.raises(AuthRefused, match="not right"):
        gate.check("s1", "111111111111")


@pytest.mark.safety
def test_registration_rate_limits_per_session_even_for_the_right_code(gate):
    for _ in range(gate.per_session):
        with pytest.raises(AuthRefused, match="not right"):
            gate.check("s1", "111111111111")
    with pytest.raises(AuthRefused, match="Too many"):
        gate.check("s1", CODE)  # locked out: the right code learns nothing either
    assert gate.check("s2", CODE).session == "s2"  # another session is unaffected


@pytest.mark.safety
def test_registration_rate_limits_across_sessions(gate):
    for i in range(gate.overall):
        with pytest.raises(AuthRefused, match="not right"):
            gate.check(f"s{i}", "111111111111")
    with pytest.raises(AuthRefused, match="Too many"):
        gate.check("fresh", CODE)


def test_registration_lockout_ends_after_a_quiet_window(kv):
    clock = Clock()
    h, s = make_code_hash(CODE)
    gate = RegistrationGate(kv, h, s, clock=clock)
    for _ in range(gate.per_session):
        with pytest.raises(AuthRefused):
            gate.check("s1", "111111111111")
    with pytest.raises(AuthRefused, match="Too many"):
        gate.check("s1", CODE)
    clock.t += 2 * gate.window_s  # the window of the attempts and the next have both passed
    assert gate.check("s1", CODE)


@pytest.mark.safety
def test_registration_limit_cannot_be_doubled_across_a_window_boundary(kv):
    """The global limit holds over any hour: attempts just before a window boundary still
    count just after it (a per-clock-hour counter allowed 2 x 10 in a few seconds)."""
    clock = Clock(10 * CODE_WINDOW_S - 1)  # one second before a boundary
    h, s = make_code_hash(CODE)
    gate = RegistrationGate(kv, h, s, clock=clock)
    for i in range(gate.overall):
        with pytest.raises(AuthRefused, match="not right"):
            gate.check(f"s{i}", "111111111111")
    clock.t += 2  # the next clock hour
    for i in range(gate.overall):
        with pytest.raises(AuthRefused, match="Too many"):
            gate.check(f"t{i}", "111111111111" if i else CODE)
    clock.t += 2 * CODE_WINDOW_S  # refused attempts count too; after a quiet window: unlocked
    assert gate.check("fresh", CODE).session == "fresh"


def test_registration_refuses_readably_when_the_store_is_down(gate, monkeypatch):
    """(also covers a failing read of the previous window's count)"""
    monkeypatch.setattr(gate.kv, "get_int", lambda *a: (_ for _ in ()).throw(KVError("x")))
    with pytest.raises(AuthRefused, match="unavailable"):
        gate.check("s0", CODE)
    monkeypatch.undo()

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

    assert cli.main.__defaults__ is not None and cli.main.__defaults__[0] is cli._read
    # on a terminal the code is read hidden, through getpass
    seen: list[str] = []
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: seen.append(prompt) or "42")
    assert cli._read("code: ") == "42" and seen == ["code: "]
    out: list[str] = []
    assert cli.main(read=lambda _: "1234", write=out.append) == 2
    answers = iter([CODE, "999999999999"])
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
    h, s = make_code_hash(CODE)
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


@pytest.mark.safety
@pytest.mark.parametrize(
    ("rp", "origin"),
    [
        ("localhost", "http://localhost.evil.example"),  # passed the old prefix check
        ("localhost", "http://localhost:8501.evil.example"),
        ("localhost", "http://localhost@evil.example"),
        (RP, "https://citewatch.streamlit.app.evil.example"),
        (RP, "https://evil.example"),
        (RP, "https://citewatch.streamlit.app/path"),
        (RP, "https://citewatch.streamlit.app?q=1"),
        (RP, "https://user@citewatch.streamlit.app"),
        (RP, "https://citewatch.streamlit.app:notaport"),
        (RP, "ftp://citewatch.streamlit.app"),
        ("", ORIGIN),
    ],
)
def test_origin_is_checked_exactly_not_by_prefix(kv, rp, origin):
    with pytest.raises(ValueError):
        Passkeys(rp, origin, CredentialStore(kv))


@pytest.mark.parametrize(
    ("rp", "origin", "exact"),
    [
        (RP, ORIGIN + "/", ORIGIN),
        (RP, "https://CITEWATCH.streamlit.app:8443", "https://citewatch.streamlit.app:8443"),
        ("streamlit.app", ORIGIN, ORIGIN),  # a host under the RP ID is allowed by WebAuthn
        ("localhost", "http://localhost:8501", "http://localhost:8501"),
        ("localhost", "https://localhost", "https://localhost"),
    ],
)
def test_exact_origin_keeps_scheme_host_and_port(kv, rp, origin, exact):
    assert Passkeys(rp, origin, CredentialStore(kv)).origin == exact
    assert exact_origin(origin, rp) == exact


def test_an_origin_with_another_port_is_refused_at_sign_in(kv, gate):
    pk = Passkeys(RP, ORIGIN, CredentialStore(kv), clock=Clock())
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)
    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused, match="could not be verified"):
        pk.finish_authentication(pending, auth.get(options, origin=ORIGIN + ":8443"))


# --- single use and store failures --------------------------------------------------------------


@pytest.mark.safety
def test_a_pending_sign_in_verifies_once_even_with_a_zero_counter(pk, gate):
    """Many platform passkeys always report counter 0, so the counter check cannot stop a
    replay; the pending ceremony itself must be single-use."""
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)
    options, pending = pk.authentication_options()
    response = auth.get(options, count=0)
    assert pk.finish_authentication(pending, response).sign_count == 0
    with pytest.raises(AuthRefused, match="already used"):
        pk.finish_authentication(pending, response)


@pytest.mark.safety
def test_a_failed_finish_also_spends_the_pending(pk, gate):
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)
    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused, match="could not be verified"):
        pk.finish_authentication(pending, auth.get(options, user_verified=False))
    with pytest.raises(AuthRefused, match="already used"):
        pk.finish_authentication(pending, auth.get(options, count=0))


@pytest.mark.safety
def test_a_pending_registration_verifies_once(pk, gate, kv):
    auth = SoftAuthenticator(RP, ORIGIN)
    options, pending = pk.registration_options(gate.check("s1", CODE), "s1")
    response = auth.create(options)
    pk.finish_registration(pending, response)
    kv.hset("passkeys", auth.id, "")  # even if the stored record were gone or broken
    with pytest.raises(AuthRefused, match="already used"):
        pk.finish_registration(pending, response)


@pytest.mark.safety
@pytest.mark.parametrize("method", ["hget", "hset"])
@pytest.mark.parametrize("error", [KVError("https://secret-kv.example token=abc"), OSError("x")])
def test_store_failures_in_ceremonies_are_a_refusal_not_a_traceback(
    pk, gate, kv, monkeypatch, method, error
):
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)

    def boom(*a, **k):
        raise error

    monkeypatch.setattr(kv, method, boom)
    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused) as signed:
        pk.finish_authentication(pending, auth.get(options))
    other = SoftAuthenticator(RP, ORIGIN)
    options, pending = pk.registration_options(gate.check("s2", CODE), "s2")
    with pytest.raises(AuthRefused) as registered:
        pk.finish_registration(pending, other.create(options))
    for exc in (signed.value, registered.value):
        assert exc.reason == STORE_DOWN and exc.__cause__ is None
        assert "secret-kv" not in exc.reason
    if method == "hget":
        monkeypatch.setattr(kv, "hlen", boom)
        with pytest.raises(AuthRefused, match="unavailable"):
            pk.store.count()


def test_a_corrupt_stored_passkey_is_a_refusal(pk, gate, kv):
    auth = SoftAuthenticator(RP, ORIGIN)
    _register(pk, gate, auth)
    kv.hset("passkeys", auth.id, "{not json")
    options, pending = pk.authentication_options()
    with pytest.raises(AuthRefused, match="unavailable"):
        pk.finish_authentication(pending, auth.get(options))
