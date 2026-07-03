"""Ed25519 signing / verification and key management for standard bundles.

Signing is MANDATORY. The server signs each bundle with an Ed25519 private key;
the Pad verifies with the matching public key (shipped as an app asset) BEFORE
parsing any bundle content beyond the outer envelope. There is no "skip
verification" path.

Key management (server edition):
  - ``QC_BUNDLE_SIGNING_KEY``      : filesystem path to a PEM Ed25519 private key.
  - ``QC_BUNDLE_SIGNING_KEY_PEM``  : PEM private key contents inline (env/secret).
  - ``QC_BUNDLE_PUBLIC_KEY`` / ``QC_BUNDLE_PUBLIC_KEY_PEM`` : optional explicit
    public key for verify-side use; otherwise derived from the private key.

Only key *fingerprints* are ever logged — never key material.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger("qc.bundle.signing")


class SigningKeyError(RuntimeError):
    """Raised when the signing key is missing or unparseable in server edition."""


def public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    """Short, stable, non-secret fingerprint: first 16 hex of SHA-256(raw key)."""
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class BundleSigner:
    """Holds the private key and signs canonical bundle bytes."""

    _private_key: Ed25519PrivateKey

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._private_key.public_key()

    @property
    def fingerprint(self) -> str:
        return public_key_fingerprint(self.public_key)

    def sign(self, payload: bytes) -> str:
        """Return base64 Ed25519 signature over ``payload``."""
        return base64.b64encode(self._private_key.sign(payload)).decode("ascii")

    def public_key_pem(self) -> str:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def public_key_b64_raw(self) -> str:
        """Raw 32-byte public key, base64 — the form shipped to the Pad asset."""
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")


def verify(public_key: Ed25519PublicKey, payload: bytes, signature_b64: str) -> bool:
    """Verify a base64 Ed25519 signature. Returns False on any failure."""
    try:
        public_key.verify(base64.b64decode(signature_b64), payload)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ── Key loading ───────────────────────────────────────────────────────────────


def _load_private_from_pem(pem: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError("QC bundle signing key is not an Ed25519 private key")
    return key


def load_signer() -> BundleSigner:
    """Load the signer from env. Raises SigningKeyError if unavailable/invalid."""
    pem_inline = os.getenv("QC_BUNDLE_SIGNING_KEY_PEM")
    key_path = os.getenv("QC_BUNDLE_SIGNING_KEY")
    pem_bytes: Optional[bytes] = None
    source = None
    if pem_inline:
        pem_bytes = pem_inline.encode("utf-8")
        source = "QC_BUNDLE_SIGNING_KEY_PEM"
    elif key_path:
        if not os.path.isfile(key_path):
            raise SigningKeyError(f"QC_BUNDLE_SIGNING_KEY path not found: {key_path}")
        with open(key_path, "rb") as fh:
            pem_bytes = fh.read()
        source = f"QC_BUNDLE_SIGNING_KEY={key_path}"
    if pem_bytes is None:
        raise SigningKeyError(
            "No bundle signing key configured. Set QC_BUNDLE_SIGNING_KEY (path) or "
            "QC_BUNDLE_SIGNING_KEY_PEM (inline PEM)."
        )
    signer = BundleSigner(_load_private_from_pem(pem_bytes))
    logger.info("Loaded bundle signing key from %s (fingerprint=%s)", source, signer.fingerprint)
    return signer


def load_public_key() -> Ed25519PublicKey:
    """Load the verify-side public key: explicit env, else derived from private."""
    pem_inline = os.getenv("QC_BUNDLE_PUBLIC_KEY_PEM")
    path = os.getenv("QC_BUNDLE_PUBLIC_KEY")
    if pem_inline:
        key = serialization.load_pem_public_key(pem_inline.encode("utf-8"))
    elif path and os.path.isfile(path):
        with open(path, "rb") as fh:
            key = serialization.load_pem_public_key(fh.read())
    else:
        return load_signer().public_key
    if not isinstance(key, Ed25519PublicKey):
        raise SigningKeyError("Configured QC bundle public key is not Ed25519")
    return key


def validate_signing_key_at_startup() -> None:
    """Server-edition startup check: the signing key must be present and valid.

    Called from app lifespan only in the server edition. Logs the fingerprint
    (never the key). Raises SigningKeyError to fail startup loudly if misconfigured.
    """
    signer = load_signer()
    logger.info("Bundle signing key OK (fingerprint=%s)", signer.fingerprint)


def generate_keypair_pem() -> tuple[bytes, bytes]:
    """Generate a fresh Ed25519 keypair as (private_pem, public_pem). For key
    provisioning and tests — not called on the request path."""
    priv = Ed25519PrivateKey.generate()
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem
