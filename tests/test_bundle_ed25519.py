"""Canonical Ed25519 ``.tar.gz`` bundle format — sign/verify, fail-closed."""
from __future__ import annotations

import io
import tarfile

import pytest

from src.qc_model.bundle import ed25519 as b


@pytest.fixture()
def signer():
    priv_pem, _ = b.generate_keypair_pem()
    return b.BundleSigner(b._load_private_from_pem(priv_pem))


def _manifest():
    return {
        "manifest_version": 1,
        "tenant_id": "t1",
        "bundle_version": "1.0.0",
        "skus": [{"sku_id": "s1", "item_number": "FLW-001", "standard_revision_id": "r1"}],
    }


def test_round_trip_verifies(signer):
    arch = b.build_signed_archive(_manifest(), [("photos/p1.jpg", b"\x89PNGdata")], signer)
    manifest = b.verify_signed_archive(arch.archive_bytes, signer.public_key)
    assert manifest["bundle_version"] == "1.0.0"
    assert arch.signing_key_fingerprint == signer.fingerprint


def test_wrong_key_rejected(signer):
    arch = b.build_signed_archive(_manifest(), [], signer)
    other_priv, _ = b.generate_keypair_pem()
    other_pub = b.BundleSigner(b._load_private_from_pem(other_priv)).public_key
    with pytest.raises(b.BundleVerifyError):
        b.verify_signed_archive(arch.archive_bytes, other_pub)


def test_tampered_photo_rejected(signer):
    arch = b.build_signed_archive(_manifest(), [("photos/p1.jpg", b"original")], signer)
    # Rebuild the archive with a tampered photo but the original manifest/sig.
    tampered = _repack(arch.archive_bytes, replace={"photos/p1.jpg": b"tampered!!"})
    with pytest.raises(b.BundleVerifyError):
        b.verify_signed_archive(tampered, signer.public_key)


def test_tampered_manifest_rejected(signer):
    arch = b.build_signed_archive(_manifest(), [], signer)
    tampered = _repack(arch.archive_bytes, replace={b.MANIFEST_NAME: b'{"bundle_version":"9.9.9"}'})
    with pytest.raises(b.BundleVerifyError):
        b.verify_signed_archive(tampered, signer.public_key)


def test_missing_signature_rejected(signer):
    arch = b.build_signed_archive(_manifest(), [], signer)
    stripped = _repack(arch.archive_bytes, drop={b.SIGNATURE_NAME})
    with pytest.raises(b.BundleVerifyError):
        b.verify_signed_archive(stripped, signer.public_key)


def test_extra_unlisted_payload_rejected(signer):
    arch = b.build_signed_archive(_manifest(), [], signer)
    smuggled = _repack(arch.archive_bytes, add={"photos/evil.jpg": b"smuggled"})
    with pytest.raises(b.BundleVerifyError):
        b.verify_signed_archive(smuggled, signer.public_key)


def test_load_signer_fails_closed_without_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for var in (
        "QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM",
        "QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(b.SigningKeyError):
        b.load_signer()


def test_canonical_env_vars_load(monkeypatch):
    priv_pem, pub_pem = b.generate_keypair_pem()
    monkeypatch.setenv("QC_BUNDLE_SIGNING_PRIVATE_KEY_PEM", priv_pem.decode())
    monkeypatch.setenv("QC_BUNDLE_VERIFY_PUBLIC_KEY_PEM", pub_pem.decode())
    signer = b.load_signer()
    arch = b.build_signed_archive(_manifest(), [], signer)
    assert b.verify_signed_archive(arch.archive_bytes, b.load_public_key())["tenant_id"] == "t1"


def _repack(archive_bytes, replace=None, drop=None, add=None):
    replace = replace or {}
    drop = drop or set()
    add = add or {}
    out = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as src, \
            tarfile.open(fileobj=out, mode="w:gz") as dst:
        for m in src.getmembers():
            if m.name in drop:
                continue
            data = replace.get(m.name, src.extractfile(m).read())
            info = tarfile.TarInfo(m.name)
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))
        for name, data in add.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            dst.addfile(info, io.BytesIO(data))
    return out.getvalue()
