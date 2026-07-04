"""Canonical bundle signing: Ed25519 over a ``.tar.gz`` archive.

This is the **single** production bundle format for the whole system. The server
holds an Ed25519 *private* key and signs; a deployed Pad holds only the matching
*public* key and verifies offline — which is exactly why HMAC is unsuitable
(HMAC would force the verifier to hold the signing secret). There is no
skip-verification path.

Canonical archive layout (``.tar.gz``)::

    manifest.json        # the standard: SKUs, revisions, detection points
    checksum.sha256      # "<sha256>␠␠<path>" per line for manifest + every photo
    bundle.sig           # base64 Ed25519 signature over manifest + checksum
    photos/...           # the reference photo payload

The signature covers ``manifest.json`` + ``checksum.sha256``; the checksum covers
every payload file — so tampering with a photo, the checksum, or the manifest is
always rejected. Verification runs on the archive envelope *before* any manifest
content is trusted.

Canonical environment variables (no ambiguous ``QC_BUNDLE_SIGNING_KEY``):

* Server (signer):
    - ``QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM``   — inline PEM private key, or
    - ``QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH``  — path to a PEM private key.
* Pad / verifier:
    - ``QC_BUNDLE_VERIFY_PUBLIC_KEY_PEM``     — inline PEM public key, or
    - ``QC_BUNDLE_VERIFY_PUBLIC_KEY_PATH``    — path to a PEM public key.

Under ``APP_ENV=test`` and with no key configured, an ephemeral keypair is
generated once per process so the suite can round-trip without provisioning
keys; outside the test environment a missing key is a hard error.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import tarfile
from dataclasses import dataclass
from typing import Iterable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

logger = logging.getLogger("qc.bundle.ed25519")

MANIFEST_NAME = "manifest.json"
CHECKSUM_NAME = "checksum.sha256"
SIGNATURE_NAME = "bundle.sig"
SIGNATURE_ALGO = "ed25519"


class SigningKeyError(RuntimeError):
    """Signing key missing or unparseable in a non-test environment."""


class BundleVerifyError(RuntimeError):
    """A bundle failed signature / checksum / manifest verification (fail-closed)."""


def _app_env() -> str:
    return os.getenv("APP_ENV", "production").lower()


def _canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _signed_payload(manifest_bytes: bytes, checksum_bytes: bytes) -> bytes:
    return manifest_bytes + b"\n" + checksum_bytes


def public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return _sha256(raw)[:16]


# ── Signer ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BundleSigner:
    _private_key: Ed25519PrivateKey

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._private_key.public_key()

    @property
    def fingerprint(self) -> str:
        return public_key_fingerprint(self.public_key)

    def sign(self, payload: bytes) -> str:
        return base64.b64encode(self._private_key.sign(payload)).decode("ascii")

    def public_key_pem(self) -> str:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")


def verify_signature(public_key: Ed25519PublicKey, payload: bytes, signature_b64: str) -> bool:
    """Fail-closed: return False on any error (bad sig, bad base64, wrong key)."""
    try:
        public_key.verify(base64.b64decode(signature_b64), payload)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ── Key loading (canonical env vars) ──────────────────────────────────────────

_EPHEMERAL_TEST_KEY: Optional[Ed25519PrivateKey] = None


def _ephemeral_test_key() -> Ed25519PrivateKey:
    global _EPHEMERAL_TEST_KEY
    if _EPHEMERAL_TEST_KEY is None:
        _EPHEMERAL_TEST_KEY = Ed25519PrivateKey.generate()
    return _EPHEMERAL_TEST_KEY


def _load_private_from_pem(pem: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError("configured bundle signing key is not an Ed25519 private key")
    return key


def load_signer() -> BundleSigner:
    """Load the server signer from the canonical env vars (fail-closed)."""
    pem_inline = os.getenv("QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM")
    key_path = os.getenv("QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH")
    if pem_inline:
        return BundleSigner(_load_private_from_pem(pem_inline.encode("utf-8")))
    if key_path:
        if not os.path.isfile(key_path):
            raise SigningKeyError(f"QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH not found: {key_path}")
        with open(key_path, "rb") as fh:
            return BundleSigner(_load_private_from_pem(fh.read()))
    if _app_env() == "test":
        return BundleSigner(_ephemeral_test_key())
    raise SigningKeyError(
        "No bundle signing key configured. Set QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM "
        "or QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH."
    )


def load_public_key() -> Ed25519PublicKey:
    """Load the verify-side public key: explicit env, else the signer's public key."""
    pem_inline = os.getenv("QC_BUNDLE_VERIFY_PUBLIC_KEY_PEM")
    path = os.getenv("QC_BUNDLE_VERIFY_PUBLIC_KEY_PATH")
    if pem_inline:
        key = serialization.load_pem_public_key(pem_inline.encode("utf-8"))
    elif path and os.path.isfile(path):
        with open(path, "rb") as fh:
            key = serialization.load_pem_public_key(fh.read())
    else:
        # Derived from the signer (dev/test, or single-node deployments).
        return load_signer().public_key
    if not isinstance(key, Ed25519PublicKey):
        raise SigningKeyError("configured QC bundle public key is not Ed25519")
    return key


def validate_signing_key_at_startup() -> None:
    """Server-edition startup check: signing key present and valid, else fail loud."""
    signer = load_signer()
    logger.info("Bundle signing key OK (fingerprint=%s)", signer.fingerprint)


def generate_keypair_pem() -> tuple[bytes, bytes]:
    """(private_pem, public_pem) for provisioning / tests — never on the hot path."""
    priv = Ed25519PrivateKey.generate()
    return (
        priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )


# ── Archive build / verify ────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignedArchive:
    archive_bytes: bytes
    manifest: dict
    manifest_sha256: str
    archive_sha256: str
    signature_b64: str
    signing_key_fingerprint: str


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))


def build_signed_archive(
    manifest: dict,
    photos: Iterable[tuple[str, bytes]],
    signer: Optional[BundleSigner] = None,
) -> SignedArchive:
    """Build a signed ``.tar.gz`` bundle. ``photos`` is ``(relpath, bytes)`` pairs."""
    signer = signer or load_signer()
    manifest_bytes = _canonical_json(manifest)

    checksum_lines = [f"{_sha256(manifest_bytes)}  {MANIFEST_NAME}"]
    photo_items = list(photos)
    for relpath, data in photo_items:
        checksum_lines.append(f"{_sha256(data)}  {relpath}")
    checksum_bytes = ("\n".join(checksum_lines) + "\n").encode("utf-8")

    signature_b64 = signer.sign(_signed_payload(manifest_bytes, checksum_bytes))

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add_bytes(tar, MANIFEST_NAME, manifest_bytes)
        _add_bytes(tar, CHECKSUM_NAME, checksum_bytes)
        _add_bytes(tar, SIGNATURE_NAME, signature_b64.encode("ascii"))
        for relpath, data in photo_items:
            _add_bytes(tar, relpath, data)
    archive_bytes = buf.getvalue()

    return SignedArchive(
        archive_bytes=archive_bytes,
        manifest=manifest,
        manifest_sha256=_sha256(manifest_bytes),
        archive_sha256=_sha256(archive_bytes),
        signature_b64=signature_b64,
        signing_key_fingerprint=signer.fingerprint,
    )


def verify_signed_archive(archive_bytes: bytes, public_key: Optional[Ed25519PublicKey] = None) -> dict:
    """Verify a ``.tar.gz`` bundle fail-closed and return the parsed manifest.

    Order: signature over (manifest + checksum) FIRST, then per-file checksums,
    then parse the manifest. Any failure raises :class:`BundleVerifyError`.
    """
    public_key = public_key or load_public_key()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}
            for required in (MANIFEST_NAME, CHECKSUM_NAME, SIGNATURE_NAME):
                if required not in members:
                    raise BundleVerifyError(f"bundle missing {required}")
            manifest_bytes = tar.extractfile(members[MANIFEST_NAME]).read()
            checksum_bytes = tar.extractfile(members[CHECKSUM_NAME]).read()
            signature_b64 = tar.extractfile(members[SIGNATURE_NAME]).read().decode("ascii").strip()

            # 1) signature over manifest + checksum
            if not verify_signature(public_key, _signed_payload(manifest_bytes, checksum_bytes), signature_b64):
                raise BundleVerifyError("invalid bundle signature")

            # 2) checksum covers manifest + every payload file
            expected: dict[str, str] = {}
            for line in checksum_bytes.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                digest, _, path = line.partition("  ")
                expected[path] = digest
            if expected.get(MANIFEST_NAME) != _sha256(manifest_bytes):
                raise BundleVerifyError("manifest checksum mismatch")
            present = {n for n in members
                       if n not in (CHECKSUM_NAME, SIGNATURE_NAME)}
            # Every checksum-listed file must actually be in the archive — a
            # dropped payload (missing photo file) is rejected, not silently
            # ignored.
            missing = sorted(set(expected) - present)
            if missing:
                raise BundleVerifyError(f"missing payload files: {missing}")
            # ...and no file may be present that the checksum does not cover.
            for name, member in members.items():
                if name in (MANIFEST_NAME, CHECKSUM_NAME, SIGNATURE_NAME):
                    continue
                if name not in expected:
                    raise BundleVerifyError(f"unlisted payload file: {name}")
                if _sha256(tar.extractfile(member).read()) != expected[name]:
                    raise BundleVerifyError(f"payload checksum mismatch: {name}")

            # 3) only now is the manifest safe to parse/trust
            return json.loads(manifest_bytes)
    except BundleVerifyError:
        raise
    except (tarfile.TarError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise BundleVerifyError(f"unreadable bundle archive: {exc}") from exc
