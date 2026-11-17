"""Passkey sign-in for live mode (DEM-02, OWNER D-58, D-59).

Registering a passkey needs the owner's numeric registration code. The code is never stored:
the host's secret store holds a salted PBKDF2-SHA256 hash and its salt, the check is a
constant-time compare, and attempts are rate-limited in the shared KV (per session and across
all sessions), counted before the compare so a locked-out caller learns nothing. After
registration, sign-in is by passkey alone.

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
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from citewatch.demo.kv import KV

HASH_SCHEME = "pbkdf2_sha256"
HASH_ITERATIONS = 600_000  # OWASP 2023 guidance for PBKDF2-HMAC-SHA256
MIN_CODE_DIGITS = 8
MAX_CODE_DIGITS = 32
CODE_TRIES_PER_SESSION = 3
CODE_TRIES_GLOBAL = 10  # per window, across every visitor: 10^8 codes take ~1,000 years
CODE_WINDOW_S = 3600
CHALLENGE_TTL_S = 300
CEREMONY_TIMEOUT_MS = 120_000
CREDENTIALS = "passkeys"
RP_NAME = "citewatch demo"


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
    if not valid_code(code):
        raise ValueError(
            f"the registration code must be {MIN_CODE_DIGITS} to {MAX_CODE_DIGITS} digits"
        )
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode("ascii"), salt, iterations)
    return f"{HASH_SCHEME}${iterations}${digest.hex()}", salt.hex()


def check_code(code: str, code_hash: str, salt_hex: str) -> bool:
    """True when `code` matches the stored hash; the digests are compared in constant time."""
    try:
        scheme, iterations, expected = code_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        want = bytes.fromhex(expected)
        rounds = int(iterations)
    except ValueError:
        return False
    if scheme != HASH_SCHEME or rounds < 1 or not salt or not want:
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
        code is refused until the window passes."""
        if not session:
            raise AuthRefused("No session.")
        window = int(self._clock() // self.window_s)
        ttl = self.window_s * 2
        sid = hashlib.sha256(session.encode("utf-8")).hexdigest()[:24]
        try:
            mine = self.kv.incr(f"regcode:s:{sid}:{window}", 1, ttl)
            everyone = self.kv.incr(f"regcode:all:{window}", 1, ttl)
        except Exception:
            raise AuthRefused("Registration is unavailable right now; try again later.") from None
        if mine > self.per_session or everyone > self.overall:
            raise AuthRefused("Too many registration attempts. Try again in an hour.")
        if not check_code(code, self._hash, self._salt):
            raise AuthRefused("That registration code is not right.")
        return RegistrationGrant(session=session, expires=self._clock() + CHALLENGE_TTL_S)


# --- WebAuthn ceremonies -----------------------------------------------------------------------


@dataclass(frozen=True)
class Pending:
    """A ceremony in progress: its one-time challenge, kept server-side in session memory."""

    kind: str  # "register" or "sign_in"
    challenge: bytes
    expires: float
    user_id: bytes = b""


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
    """Registered passkeys in the shared KV (a hash keyed by credential id)."""

    def __init__(self, kv: KV) -> None:
        self.kv = kv

    def get(self, credential_id: str) -> StoredCredential | None:
        raw = self.kv.hget(CREDENTIALS, credential_id)
        return None if raw is None else StoredCredential.from_json(credential_id, raw)

    def put(self, cred: StoredCredential) -> None:
        self.kv.hset(CREDENTIALS, cred.credential_id, cred.to_json())

    def count(self) -> int:
        return self.kv.hlen(CREDENTIALS)


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
        if not rp_id or not origin.startswith(("https://", "http://localhost")):
            raise ValueError("passkeys need an RP ID and an https origin (or http://localhost)")
        self.rp_id = rp_id
        self.origin = origin.rstrip("/")
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
        if pending.kind != kind or pending.expires < self._clock():
            raise AuthRefused("That passkey request expired; start again.")
