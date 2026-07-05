"""Canonical bundle manifest schema + signature/checksum verification (S0 contract).

This module is the **single source of truth** for the bundle manifest format
shared between the publisher (S2 studio, which builds+signs a bundle) and the
consumers (S3 admin bundle management, and the Pad which pulls/imports a
bundle). Sessions must not define a competing format — build manifests through
:func:`build_manifest` and verify them through :func:`verify_bundle`.

## Manifest shape (version 1)

```json
{
  "manifest_version": 1,
  "bundle_version": "1.4.0",
  "tenant_id": "acme",
  "created_at": "2026-07-03T10:00:00+00:00",
  "created_by": "studio@acme",
  "skus": [
    {"sku_id": "sku_1", "item_number": "SKU-1",
     "standard_revision_id": "rev_1", "revision_no": 3}
  ],
  "photos": [
    {"photo_id": "ph_1", "sku_id": "sku_1", "sha256": "<hex>", "path": "photos/ph_1.jpg"}
  ],
  "sku_count": 1,
  "standard_revision_count": 1
}
```

## Security model (§7.3)

* Every bundle **must** be signed. An unsigned bundle is rejected.
* Verification is **fail-closed**: any failure (missing signature, tampered
  manifest, bad checksum, unknown algorithm) raises
  :class:`BundleVerificationError`. There is deliberately **no**
  ``skip_verification`` flag anywhere in the call path.
* The signature covers the SHA-256 of the *canonical* JSON encoding of the
  manifest, so re-ordering keys or reformatting cannot slip past.
* Each photo carries its own SHA-256; :func:`verify_photo_checksums` compares
  the manifest's declared digests against the digests actually present.

Signing/verification delegates to the canonical Ed25519 signer in
:mod:`src.qc_model.bundle.ed25519` — the single production bundle format. The
server signs with its private key and a deployed Pad verifies with the matching
public key it can hold safely; there is no HMAC production path (which would
require the verifier to hold the signing secret) and no unsigned path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from src.qc_model.bundle import ed25519 as _ed

MANIFEST_VERSION = 1
# The single production signature format. Ed25519 lets a deployed Pad verify
# with a public key it can hold safely; HMAC (which would require the verifier
# to hold the signing secret) is not a supported production format.
DEFAULT_SIGNATURE_ALGO = "ed25519"
_SUPPORTED_ALGOS = {"ed25519"}


class BundleVerificationError(Exception):
    """Raised when a bundle fails verification. Callers must fail closed."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


# ── Manifest construction ────────────────────────────────────────────────────


def build_manifest(
    *,
    bundle_version: str,
    tenant_id: str,
    skus: Iterable[Mapping[str, Any]],
    photos: Iterable[Mapping[str, Any]],
    created_by: str = "",
    created_at: Optional[datetime] = None,
) -> dict:
    """Build a manifest dict from bundle contents.

    ``skus`` entries need ``sku_id``, ``item_number``, ``standard_revision_id``,
    ``revision_no``.  ``photos`` entries need ``photo_id``, ``sku_id``,
    ``sha256``, ``path``.  Counts are derived, never trusted from the caller.
    """
    sku_list = [
        {
            "sku_id": s["sku_id"],
            "item_number": s.get("item_number", ""),
            "standard_revision_id": s["standard_revision_id"],
            "revision_no": int(s.get("revision_no", 0)),
        }
        for s in skus
    ]
    photo_list = [
        {
            "photo_id": p["photo_id"],
            "sku_id": p.get("sku_id", ""),
            "sha256": p["sha256"],
            "path": p.get("path", ""),
        }
        for p in photos
    ]
    distinct_revisions = {s["standard_revision_id"] for s in sku_list}
    created = created_at or datetime.now(timezone.utc)
    return {
        "manifest_version": MANIFEST_VERSION,
        "bundle_version": bundle_version,
        "tenant_id": tenant_id,
        "created_at": created.astimezone(timezone.utc).isoformat(),
        "created_by": created_by,
        "skus": sku_list,
        "photos": photo_list,
        "sku_count": len(sku_list),
        "standard_revision_count": len(distinct_revisions),
    }


def canonical_json(manifest: Mapping[str, Any]) -> str:
    """Deterministic JSON encoding used for hashing and signing.

    Sorted keys + compact separators so byte output is stable regardless of how
    the dict was assembled.
    """
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


# ── Signing ──────────────────────────────────────────────────────────────────


def sign_manifest(manifest: Mapping[str, Any], algo: str = DEFAULT_SIGNATURE_ALGO) -> str:
    """Return a base64 Ed25519 signature over the canonical manifest bytes."""
    if algo not in _SUPPORTED_ALGOS:
        raise BundleVerificationError("unknown_signature_algo", algo)
    return _ed.load_signer().sign(canonical_json(manifest).encode("utf-8"))


@dataclass
class SignedBundle:
    """A manifest plus its signature envelope, as stored/transported."""

    manifest: dict
    signature: str
    signature_algo: str = DEFAULT_SIGNATURE_ALGO
    manifest_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.manifest_sha256:
            self.manifest_sha256 = compute_manifest_sha256(self.manifest)


def create_signed_bundle(
    *,
    bundle_version: str,
    tenant_id: str,
    skus: Iterable[Mapping[str, Any]],
    photos: Iterable[Mapping[str, Any]],
    created_by: str = "",
    created_at: Optional[datetime] = None,
    algo: str = DEFAULT_SIGNATURE_ALGO,
) -> SignedBundle:
    """Build + sign a bundle in one step (the publisher path)."""
    manifest = build_manifest(
        bundle_version=bundle_version,
        tenant_id=tenant_id,
        skus=skus,
        photos=photos,
        created_by=created_by,
        created_at=created_at,
    )
    signature = sign_manifest(manifest, algo=algo)
    return SignedBundle(manifest=manifest, signature=signature, signature_algo=algo)


# ── Verification (fail-closed) ────────────────────────────────────────────────


def verify_signature(
    manifest: Mapping[str, Any],
    signature: Optional[str],
    algo: str = DEFAULT_SIGNATURE_ALGO,
) -> None:
    """Raise :class:`BundleVerificationError` unless the signature is valid.

    A missing/empty signature is rejected — there is no unsigned path.
    """
    if not signature:
        raise BundleVerificationError("missing_signature")
    if algo not in _SUPPORTED_ALGOS:
        raise BundleVerificationError("unknown_signature_algo", algo)
    if not _ed.verify_signature(
        _ed.load_public_key(), canonical_json(manifest).encode("utf-8"), signature
    ):
        raise BundleVerificationError("invalid_signature")


def verify_manifest_checksum(manifest: Mapping[str, Any], expected_sha256: Optional[str]) -> None:
    """Verify the manifest digest matches the recorded checksum, if provided."""
    actual = compute_manifest_sha256(manifest)
    if expected_sha256 and not hmac.compare_digest(actual, expected_sha256):
        raise BundleVerificationError("manifest_checksum_mismatch", actual)


def verify_photo_checksums(
    manifest: Mapping[str, Any],
    actual_checksums: Optional[Mapping[str, str]] = None,
) -> None:
    """Verify each photo declares a SHA-256 and (when provided) that it matches.

    ``actual_checksums`` maps ``photo_id`` -> hex digest of the bytes actually
    present. When omitted we only assert every photo carries a non-empty
    checksum (a manifest with an unchecksummed photo is itself invalid).
    """
    for photo in manifest.get("photos", []):
        declared = photo.get("sha256")
        if not declared:
            raise BundleVerificationError("photo_checksum_missing", str(photo.get("photo_id")))
        if actual_checksums is not None:
            actual = actual_checksums.get(photo["photo_id"])
            if actual is None:
                raise BundleVerificationError("photo_missing", str(photo["photo_id"]))
            if not hmac.compare_digest(actual, declared):
                raise BundleVerificationError("photo_checksum_mismatch", str(photo["photo_id"]))


def verify_bundle(
    bundle: SignedBundle,
    *,
    expected_manifest_sha256: Optional[str] = None,
    actual_photo_checksums: Optional[Mapping[str, str]] = None,
) -> None:
    """Full fail-closed verification of a signed bundle.

    Order: manifest shape → recorded manifest checksum → signature → photo
    checksums. Any problem raises :class:`BundleVerificationError`; there is no
    flag to skip this.
    """
    manifest = bundle.manifest
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise BundleVerificationError("unsupported_manifest_version", str(manifest.get("manifest_version")))
    if not manifest.get("bundle_version"):
        raise BundleVerificationError("missing_bundle_version")
    # Counts are authoritative-derived; a manifest whose counts lie is tampered.
    if manifest.get("sku_count") != len(manifest.get("skus", [])):
        raise BundleVerificationError("sku_count_mismatch")
    distinct_rev = {s.get("standard_revision_id") for s in manifest.get("skus", [])}
    if manifest.get("standard_revision_count") != len(distinct_rev):
        raise BundleVerificationError("standard_revision_count_mismatch")

    verify_manifest_checksum(manifest, expected_manifest_sha256 or bundle.manifest_sha256)
    verify_signature(manifest, bundle.signature, algo=bundle.signature_algo)
    verify_photo_checksums(manifest, actual_photo_checksums)
