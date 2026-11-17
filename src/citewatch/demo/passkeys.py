"""Passkey sign-in for live mode (DEM-02, OWNER D-58, D-59).

Registering a passkey needs the owner's numeric registration code. The code is never stored:
the host's secret store holds a salted PBKDF2-SHA256 hash and its salt, the check is a
constant-time compare, and attempts are rate-limited in the shared KV (per session and across
all sessions), counted before the compare so a locked-out caller learns nothing. The limits
hold over any hour, not per clock hour: an attempt counts against the current and the previous
window together, so no burst can straddle a window boundary. After registration, sign-in is by
passkey alone.

The WebAuthn ceremonies are generated and verified server-side with py_webauthn; the browser
part (navigator.credentials) is the small Streamlit component in `citewatch.demo.component`.
Passkeys are discoverable credentials with user verification required, so sign-in needs no
user name. The store keeps only what verification needs: the credential id, its public key,
its signature counter and the date it was added. No name, e-mail or IP address is kept.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from citewatch.demo.kv import KV

HASH_SCHEME = "pbkdf2_sha256"
HASH_ITERATIONS = 600_000  # OWASP 2023 guidance for PBKDF2-HMAC-SHA256; also the floor
MIN_CODE_DIGITS = 12
MAX_CODE_DIGITS = 32
CODE_TRIES_PER_SESSION = 3
CODE_TRIES_GLOBAL = 10  # in any window, across every visitor: 10^12 codes take ~10^7 years
CODE_WINDOW_S = 3600
CHALLENGE_TTL_S = 300
CEREMONY_TIMEOUT_MS = 120_000
CREDENTIALS = "passkeys"
RP_NAME = "citewatch demo"
LOG = logging.getLogger("citewatch.demo")
STORE_DOWN = "The passkey store is unavailable right now; try again later."


class AuthRefused(Exception):
    """A sign-in or registration step refused. `reason` is safe to show the visitor."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- the registration code -------------------------------------------------------------------


def valid_code(code: str) -> bool:
    return code.isascii() and code.isdigit() and MIN_CODE_DIGITS <= len(code) <= MAX_CODE_DIGITS


def make_code_hash(
    code: str, *, salt: bytes | None = None, iterations: int = HASH_ITERATIONS
) -> tuple[str, str]:
    """(`pbkdf2_sha256$<iterations>$<hex digest>`, `<hex salt>`) for the host's secret store."""
    if iterations < HASH_ITERATIONS:
        raise ValueError(f"the hash needs at least {HASH_ITERATIONS:,} PBKDF2 rounds")
    if not valid_code(code):
        raise ValueError(
            f"the registration code must be {MIN_CODE_DIGITS} to {MAX_CODE_DIGITS} digits"
        )
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode("ascii"), salt, iterations)
    return f"{HASH_SCHEME}${iterations}${digest.hex()}", salt.hex()


def check_code(code: str, code_hash: str, salt_hex: str) -> bool:
    """True when `code` matches the stored hash; the digests are compared in constant time. A
    stored hash with fewer than HASH_ITERATIONS rounds is refused outright."""
    try:
        scheme, iterations, expected = code_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        want = bytes.fromhex(expected)
        rounds = int(iterations)
    except ValueError:
        return False
    if scheme != HASH_SCHEME or rounds < HASH_ITERATIONS or not salt or not want:
        return False
    got = hashlib.pbkdf2_hmac("sha256", code.strip().encode("utf-8"), salt, rounds)
    return hmac.compare_digest(got, want) and valid_code(code.strip())


@dataclass(frozen=True)
class RegistrationGrant:
    """Proof that this session gave the right code, good for one passkey registration."""

    session: str
    expires: float


class RegistrationGate:
    def __init__(
        self,
        kv: KV,
        code_hash: str,
        code_salt: str,
        *,
        per_session: int = CODE_TRIES_PER_SESSION,
        overall: int = CODE_TRIES_GLOBAL,
        window_s: int = CODE_WINDOW_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not code_hash or not code_salt:
            raise ValueError("the registration gate needs the code hash and its salt")
        self.kv = kv
        self._hash = code_hash
        self._salt = code_salt
        self.per_session = per_session
        self.overall = overall
        self.window_s = window_s
        self._clock = clock

    def check(self, session: str, code: str) -> RegistrationGrant:
        """A grant for the right code; AuthRefused for a wrong code or too many attempts. Each
        attempt is counted before the compare, so once the limit is reached even the right
        code is refused. Each limit counts this window and the previous one together, so it
        holds over any `window_s` stretch (no double burst across a boundary); a lockout ends
        once a whole window passes with no attempts."""
        if not session:
            raise AuthRefused("No session.")
        window = int(self._clock() // self.window_s)
        sid = hashlib.sha256(session.encode("utf-8")).hexdigest()[:24]
        try:
            mine = self._count(f"regcode:s:{sid}", window)
            everyone = self._count("regcode:all", window)
        except Exception as exc:  # never echo the store's message: it can quote the URL
            LOG.warning("demo store unavailable (%s)", type(exc).__name__)
            raise AuthRefused("Registration is unavailable right now; try again later.") from None
        if mine > self.per_session or everyone > self.overall:
            raise AuthRefused("Too many registration attempts. Try again in an hour or two.")
        if not check_code(code, self._hash, self._salt):
            raise AuthRefused("That registration code is not right.")
        return RegistrationGrant(session=session, expires=self._clock() + CHALLENGE_TTL_S)

    def _count(self, prefix: str, window: int) -> int:
        """Count one attempt in `window`; return the attempts in it and in the window before.
        Each window's key lives two windows, so the previous one is still there to read."""
        now = self.kv.incr(f"{prefix}:{window}", 1, self.window_s * 2)
        return now + self.kv.get_int(f"{prefix}:{window - 1}")


# --- WebAuthn ceremonies -----------------------------------------------------------------------


@dataclass
class Pending:
    """A ceremony in progress: its one-time challenge, kept server-side in session memory.
    The first finish, pass or fail, marks it used, so it can never verify a second time."""

    kind: str  # "register" or "sign_in"
    challenge: bytes
    expires: float
    user_id: bytes = b""
    used: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class StoredCredential:
    credential_id: str  # base64url
    public_key: str  # base64url COSE key
    sign_count: int
    added: str  # ISO date

    def to_json(self) -> str:
        return json.dumps(
            {"public_key": self.public_key, "sign_count": self.sign_count, "added": self.added},
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, credential_id: str, raw: str) -> StoredCredential:
        d = json.loads(raw)
        return cls(credential_id, d["public_key"], int(d["sign_count"]), d["added"])


class CredentialStore:
    """Registered passkeys in the shared KV (a hash keyed by credential id). Any store failure
    (KVError, a database error, a corrupt record) becomes AuthRefused with a fixed message, so
    the visitor never sees a traceback or the store's own text."""

    def __init__(self, kv: KV) -> None:
        self.kv = kv

    def get(self, credential_id: str) -> StoredCredential | None:
        try:
            raw = self.kv.hget(CREDENTIALS, credential_id)
            return None if raw is None else StoredCredential.from_json(credential_id, raw)
        except Exception as exc:
            raise _store_down(exc) from None

    def put(self, cred: StoredCredential) -> None:
        try:
            self.kv.hset(CREDENTIALS, cred.credential_id, cred.to_json())
        except Exception as exc:
            raise _store_down(exc) from None

    def count(self) -> int:
        try:
            return self.kv.hlen(CREDENTIALS)
        except Exception as exc:
            raise _store_down(exc) from None


def _store_down(exc: BaseException) -> AuthRefused:
    LOG.warning("demo store unavailable (%s)", type(exc).__name__)
    return AuthRefused(STORE_DOWN)


def exact_origin(origin: str, rp_id: str) -> str:
    """The origin as `scheme://host[:port]`, checked whole rather than by prefix: https, or
    http only for the host `localhost` (local development, set explicitly in the secrets); no
    user info, path, query or fragment; a host equal to the RP ID or under it. ValueError
    otherwise. py_webauthn then compares the browser's origin with this exactly."""
    u = urlsplit(origin.strip())
    try:
        host, port = u.hostname, u.port
    except ValueError:  # a malformed port
        host, port = None, None
    rp = rp_id.strip().lower()
    secure = u.scheme == "https" or (u.scheme == "http" and host == "localhost")
    if (
        not secure
        or not host
        or not rp
        or u.username is not None
        or u.password is not None
        or u.path not in ("", "/")
        or u.query
        or u.fragment
        or (host != rp and not host.endswith("." + rp))
    ):
        raise ValueError(
            "passkeys need an RP ID and an exact origin: https://<host>[:port] at or under the "
            "RP ID (or http://localhost[:port] for local development)"
        )
    return f"{u.scheme}://{host}" + (f":{port}" if port is not None else "")


def _unverified(exc: BaseException) -> str:
    return f"The passkey could not be verified ({type(exc).__name__})."


def _credential_id(response: str | dict[str, Any]) -> str:
    try:
        d = json.loads(response) if isinstance(response, str) else response
        cid = d.get("rawId") or d.get("id")
    except (ValueError, AttributeError):
        cid = None
    if not isinstance(cid, str) or not cid:
        raise AuthRefused("The browser sent an unreadable passkey response.")
    return cid


class Passkeys:
    """Registration and sign-in ceremonies for one relying party (the deployed app)."""

    def __init__(
        self,
        rp_id: str,
        origin: str,
        store: CredentialStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.origin = exact_origin(origin, rp_id)
        self.rp_id = rp_id.strip().lower()
        self.store = store
        self._clock = clock

    def registration_options(self, grant: RegistrationGrant, session: str) -> tuple[str, Pending]:
        """Options JSON for navigator.credentials.create, and the pending ceremony. Needs a
        live grant from the registration code check for this same session."""
        from webauthn import generate_registration_options, options_to_json
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )

        if grant.session != session or grant.expires < self._clock():
            raise AuthRefused("Enter the registration code again.")
        user_id = secrets.token_bytes(16)
        opts = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=RP_NAME,
            user_id=user_id,
            user_name=f"citewatch-demo-{user_id[:3].hex()}",
            user_display_name="citewatch demo",
            timeout=CEREMONY_TIMEOUT_MS,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        pending = Pending("register", opts.challenge, self._clock() + CHALLENGE_TTL_S, user_id)
        return options_to_json(opts), pending

    def finish_registration(
        self, pending: Pending, response: str | dict[str, Any]
    ) -> StoredCredential:
        from webauthn import verify_registration_response
        from webauthn.helpers import bytes_to_base64url

        self._live(pending, "register")
        try:
            v = verify_registration_response(
                credential=response,
                expected_challenge=pending.challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                require_user_verification=True,
            )
        except Exception as exc:  # py_webauthn's message names the failed check, not secrets
            raise AuthRefused(_unverified(exc)) from None
        cid = bytes_to_base64url(v.credential_id)
        if self.store.get(cid) is not None:
            raise AuthRefused("This passkey is already registered; sign in with it.")
        cred = StoredCredential(
            credential_id=cid,
            public_key=bytes_to_base64url(v.credential_public_key),
            sign_count=v.sign_count,
            added=dt.datetime.fromtimestamp(self._clock(), dt.UTC).date().isoformat(),
        )
        self.store.put(cred)
        return cred

    def authentication_options(self) -> tuple[str, Pending]:
        from webauthn import generate_authentication_options, options_to_json
        from webauthn.helpers.structs import UserVerificationRequirement

        opts = generate_authentication_options(
            rp_id=self.rp_id,
            timeout=CEREMONY_TIMEOUT_MS,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return options_to_json(opts), Pending(
            "sign_in", opts.challenge, self._clock() + CHALLENGE_TTL_S
        )

    def finish_authentication(
        self, pending: Pending, response: str | dict[str, Any]
    ) -> StoredCredential:
        from webauthn import verify_authentication_response
        from webauthn.helpers import base64url_to_bytes

        self._live(pending, "sign_in")
        cid = _credential_id(response)
        cred = self.store.get(cid)
        if cred is None:
            raise AuthRefused("This passkey is not registered for this demo.")
        try:
            v = verify_authentication_response(
                credential=response,
                expected_challenge=pending.challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                credential_public_key=base64url_to_bytes(cred.public_key),
                credential_current_sign_count=cred.sign_count,
                require_user_verification=True,
            )
        except Exception as exc:
            raise AuthRefused(_unverified(exc)) from None
        updated = StoredCredential(cid, cred.public_key, v.new_sign_count, cred.added)
        self.store.put(updated)
        return updated

    def _live(self, pending: Pending, kind: str) -> None:
        """Refuse a pending ceremony of the wrong kind, expired or already used; otherwise mark
        it used before anything is verified, so it is spent whether the finish passes or not."""
        if pending.used:
            raise AuthRefused("That passkey request was already used; start again.")
        if pending.kind != kind or pending.expires < self._clock():
            raise AuthRefused("That passkey request expired; start again.")
        pending.used = True
