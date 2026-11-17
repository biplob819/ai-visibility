"""A software WebAuthn authenticator for tests: a P-256 key, `none` attestation and real
ECDSA signatures, so py_webauthn verifies its responses exactly as it would a browser's."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

UP, UV, AT = 0x01, 0x04, 0x40


class SoftAuthenticator:
    def __init__(self, rp_id: str, origin: str) -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.sign_count = 0

    @property
    def id(self) -> str:
        return bytes_to_base64url(self.credential_id)

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
        )

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin or self.origin}
        ).encode()

    def _rp_hash(self, rp_id: str | None) -> bytes:
        return hashlib.sha256((rp_id or self.rp_id).encode()).digest()

    def create(
        self,
        options_json: str,
        *,
        origin: str | None = None,
        rp_id: str | None = None,
        user_verified: bool = True,
    ) -> dict[str, Any]:
        o = json.loads(options_json)
        client_data = self._client_data("webauthn.create", o["challenge"], origin)
        flags = UP | AT | (UV if user_verified else 0)
        auth_data = (
            self._rp_hash(rp_id)
            + bytes([flags])
            + struct.pack(">I", self.sign_count)
            + b"\x00" * 16
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose()
        )
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(att),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def get(
        self,
        options_json: str,
        *,
        origin: str | None = None,
        user_verified: bool = True,
        count: int | None = None,
    ) -> dict[str, Any]:
        o = json.loads(options_json)
        client_data = self._client_data("webauthn.get", o["challenge"], origin)
        self.sign_count = self.sign_count + 1 if count is None else count
        flags = UP | (UV if user_verified else 0)
        auth_data = self._rp_hash(None) + bytes([flags]) + struct.pack(">I", self.sign_count)
        sig = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(sig),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }
