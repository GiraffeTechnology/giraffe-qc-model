"""Bearer + detached Ed25519 authentication for the v2 Administrator API."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


DOMAIN = "QC-XAVIER-ADMIN-V1"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class AdminAuthRejected(RuntimeError):
    def __init__(self, code: str, http_status: int = 401):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class AdminPrincipal:
    tenant_id: str
    subject: str
    key_id: str


def canonical_json(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def multipart_content_sha256(manifest: dict) -> str:
    """Digest defined by xavier-admin-runner-api.md.

    The manifest is authenticated canonically and each image digest is appended
    in manifest order. Raw image bytes are checked against those digests before
    this value is accepted.
    """
    payload = bytearray(canonical_json(manifest))
    payload.extend(b"\n")
    for image in manifest.get("images", []):
        payload.extend(str(image.get("sha256", "")).encode("ascii"))
        payload.extend(b"\n")
    return hashlib.sha256(payload).hexdigest()


def signature_payload(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    content_sha256: str,
    request_id: str = "",
) -> bytes:
    fields = [
        DOMAIN,
        method.upper(),
        path,
        timestamp,
        nonce,
        content_sha256,
        request_id,
    ]
    return ("\n".join(fields) + "\n").encode("utf-8")


def _public_key(value: str) -> Ed25519PublicKey:
    if "BEGIN PUBLIC KEY" in value:
        key = serialization.load_pem_public_key(value.encode("ascii"))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("credential public key must be Ed25519")
        return key
    raw = base64.b64decode(value, validate=True)
    return Ed25519PublicKey.from_public_bytes(raw)


class AdminAuthenticator:
    """In-memory replay guard plus provisioned credential verification.

    ``credentials`` is keyed by bearer token. Each value contains
    ``tenant_id``, ``subject``, ``key_id`` and ``public_key`` (base64 raw
    Ed25519 or PEM). Secrets/keys are deployment configuration, never defaults.
    """

    def __init__(
        self,
        credentials: Mapping[str, dict],
        *,
        max_clock_skew_seconds: int = 300,
        nonce_ttl_seconds: int = 600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._credentials = dict(credentials)
        self._max_skew = max_clock_skew_seconds
        self._nonce_ttl = nonce_ttl_seconds
        self._clock = clock
        self._nonces: dict[tuple[str, str], float] = {}
        self._nonce_lock = threading.Lock()

    def authenticate(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        content_sha256: str,
        request_id: str = "",
    ) -> AdminPrincipal:
        lower = {str(k).lower(): str(v) for k, v in headers.items()}
        authorization = lower.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AdminAuthRejected("authentication_required")
        credential = self._credentials.get(token)
        if not isinstance(credential, dict):
            raise AdminAuthRejected("device_not_authorized", 403)

        key_id = lower.get("x-qc-key-id", "")
        timestamp = lower.get("x-qc-timestamp", "")
        nonce = lower.get("x-qc-nonce", "")
        claimed_digest = lower.get("x-qc-content-sha256", "")
        signature_b64 = lower.get("x-qc-signature", "")
        if not all((key_id, timestamp, nonce, claimed_digest, signature_b64)):
            raise AdminAuthRejected("bad_signature")
        if key_id != credential.get("key_id"):
            raise AdminAuthRejected("device_not_authorized", 403)
        if claimed_digest != content_sha256:
            raise AdminAuthRejected("content_digest_mismatch")

        try:
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                raise ValueError("timezone required")
            observed_epoch = observed.astimezone(timezone.utc).timestamp()
        except ValueError as exc:
            raise AdminAuthRejected("invalid_timestamp") from exc
        now = self._clock()
        if abs(now - observed_epoch) > self._max_skew:
            raise AdminAuthRejected("timestamp_out_of_window")

        with self._nonce_lock:
            self._expire_nonces(now)
            nonce_key = (key_id, nonce)
            if nonce_key in self._nonces:
                raise AdminAuthRejected("replay_detected")

            try:
                key = _public_key(str(credential.get("public_key", "")))
                signature = base64.b64decode(signature_b64, validate=True)
                key.verify(
                    signature,
                    signature_payload(
                        method, path, timestamp, nonce, content_sha256, request_id
                    ),
                )
            except (InvalidSignature, ValueError, TypeError, binascii.Error) as exc:
                raise AdminAuthRejected("bad_signature") from exc

            self._nonces[nonce_key] = now + self._nonce_ttl
        tenant_id = str(credential.get("tenant_id", ""))
        subject = str(credential.get("subject", ""))
        if not tenant_id or not subject:
            raise AdminAuthRejected("device_not_authorized", 403)
        return AdminPrincipal(tenant_id=tenant_id, subject=subject, key_id=key_id)

    def _expire_nonces(self, now: float) -> None:
        expired = [key for key, expiry in self._nonces.items() if expiry <= now]
        for key in expired:
            self._nonces.pop(key, None)
