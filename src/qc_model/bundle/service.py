"""Bundle + workstation management service (§6, §7).

Tenant-scoped, fail-closed. This module owns bundle *history/list/download/
assign* and workstation *register/status/report* — it does NOT build or sign a
bundle (that is the studio/publisher path in S2); it records an already-signed
bundle and re-verifies it on every download.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import config
from src.db.qc_bundle_models import (
    BUNDLE_STATUS_SIGNED,
    PAIRED_STATUS_PAIRED,
    PAIRED_STATUS_PENDING,
    QCBundle,
    QCBundleAssignment,
    QCWorkstation,
)
from src.db.models import _utcnow
from src.qc_model.bundle.manifest import (
    BundleVerificationError,
    SignedBundle,
    verify_bundle,
)


class BundleNotFound(Exception):
    pass


class WorkstationNotFound(Exception):
    pass


def _uid() -> str:
    return uuid.uuid4().hex


def _secret() -> str:
    return config.bundle_signing_secret()


# ── Bundle recording (publisher hand-off) ─────────────────────────────────────


def record_signed_bundle(
    db: Session,
    *,
    tenant_id: str,
    signed: SignedBundle,
    created_by: str = "",
) -> QCBundle:
    """Persist an already-signed bundle after verifying it fail-closed.

    Called by the publisher once a bundle has been built + signed in the studio.
    A bundle that does not verify is never recorded.
    """
    if signed.manifest.get("tenant_id") != tenant_id:
        raise BundleVerificationError("tenant_mismatch", str(signed.manifest.get("tenant_id")))
    verify_bundle(signed, _secret())

    version = signed.manifest["bundle_version"]
    existing = db.scalar(
        select(QCBundle).where(
            QCBundle.tenant_id == tenant_id, QCBundle.bundle_version == version
        )
    )
    if existing is not None:
        raise BundleVerificationError("duplicate_bundle_version", version)

    bundle = QCBundle(
        id=_uid(),
        tenant_id=tenant_id,
        bundle_version=version,
        status=BUNDLE_STATUS_SIGNED,
        sku_count=signed.manifest.get("sku_count", 0),
        standard_revision_count=signed.manifest.get("standard_revision_count", 0),
        created_by=created_by or signed.manifest.get("created_by", ""),
        manifest_json=signed.manifest,
        manifest_sha256=signed.manifest_sha256,
        signature=signed.signature,
        signature_algo=signed.signature_algo,
    )
    db.add(bundle)
    db.commit()
    db.refresh(bundle)
    return bundle


def list_bundles(db: Session, tenant_id: str) -> list[QCBundle]:
    """Bundle history for a tenant, newest first."""
    return list(
        db.scalars(
            select(QCBundle)
            .where(QCBundle.tenant_id == tenant_id)
            .order_by(QCBundle.created_at.desc())
        )
    )


def get_bundle(db: Session, tenant_id: str, bundle_pk: str) -> QCBundle:
    bundle = db.scalar(
        select(QCBundle).where(QCBundle.id == bundle_pk, QCBundle.tenant_id == tenant_id)
    )
    if bundle is None:
        raise BundleNotFound(bundle_pk)
    return bundle


def _as_signed(bundle: QCBundle) -> SignedBundle:
    return SignedBundle(
        manifest=dict(bundle.manifest_json),
        signature=bundle.signature,
        signature_algo=bundle.signature_algo,
        manifest_sha256=bundle.manifest_sha256,
    )


def download_bundle(db: Session, tenant_id: str, bundle_pk: str) -> SignedBundle:
    """Return the signed bundle for download — re-verified fail-closed.

    Any tampering with the stored manifest, checksum, or signature raises
    :class:`BundleVerificationError`; there is no skip-verification path.
    """
    bundle = get_bundle(db, tenant_id, bundle_pk)
    signed = _as_signed(bundle)
    verify_bundle(signed, _secret(), expected_manifest_sha256=bundle.manifest_sha256)
    return signed


# ── Workstation management (§6) ───────────────────────────────────────────────


def register_workstation(
    db: Session,
    *,
    tenant_id: str,
    workstation_id: str,
    display_name: str,
    site_or_line: Optional[str] = None,
) -> QCWorkstation:
    existing = db.scalar(
        select(QCWorkstation).where(
            QCWorkstation.tenant_id == tenant_id,
            QCWorkstation.workstation_id == workstation_id,
        )
    )
    if existing is not None:
        return existing
    ws = QCWorkstation(
        id=_uid(),
        tenant_id=tenant_id,
        workstation_id=workstation_id,
        display_name=display_name,
        site_or_line=site_or_line,
        paired_status=PAIRED_STATUS_PENDING,
        pairing_token=_uid()[:12],
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def list_workstations(db: Session, tenant_id: str) -> list[QCWorkstation]:
    return list(
        db.scalars(
            select(QCWorkstation)
            .where(QCWorkstation.tenant_id == tenant_id)
            .order_by(QCWorkstation.created_at.desc())
        )
    )


def get_workstation(db: Session, tenant_id: str, workstation_pk: str) -> QCWorkstation:
    ws = db.scalar(
        select(QCWorkstation).where(
            QCWorkstation.id == workstation_pk, QCWorkstation.tenant_id == tenant_id
        )
    )
    if ws is None:
        raise WorkstationNotFound(workstation_pk)
    return ws


def pair_workstation(db: Session, tenant_id: str, workstation_pk: str, token: str) -> QCWorkstation:
    ws = get_workstation(db, tenant_id, workstation_pk)
    if not ws.pairing_token or token != ws.pairing_token:
        raise WorkstationNotFound("invalid_pairing_token")
    ws.paired_status = PAIRED_STATUS_PAIRED
    db.commit()
    db.refresh(ws)
    return ws


def assign_bundle(
    db: Session,
    *,
    tenant_id: str,
    workstation_pk: str,
    bundle_pk: str,
    assigned_by: str = "",
) -> QCWorkstation:
    """Assign a (verified) bundle version to a workstation.

    Verification is fail-closed: a workstation is never assigned a bundle that
    does not pass signature/checksum verification.
    """
    ws = get_workstation(db, tenant_id, workstation_pk)
    bundle = get_bundle(db, tenant_id, bundle_pk)
    verify_bundle(_as_signed(bundle), _secret(), expected_manifest_sha256=bundle.manifest_sha256)

    ws.assigned_bundle_version = bundle.bundle_version
    db.add(
        QCBundleAssignment(
            id=_uid(),
            tenant_id=tenant_id,
            workstation_pk=ws.id,
            bundle_pk=bundle.id,
            bundle_version=bundle.bundle_version,
            assigned_by=assigned_by,
        )
    )
    db.commit()
    db.refresh(ws)
    return ws


def report_from_pad(
    db: Session,
    *,
    tenant_id: str,
    workstation_pk: str,
    installed_bundle_version: Optional[str] = None,
    sync_status: Optional[str] = None,
    error: Optional[str] = None,
    outbox_upload_status: Optional[str] = None,
) -> QCWorkstation:
    """Simulated Pad import/report path (§6.5).

    A Pad calls this after importing a bundle to report its installed version,
    last sync result, and any import error. Kept intentionally small and
    side-effect-clean so Session 7 can exercise it without a real device. It
    only updates fleet status; it never changes assignment.
    """
    ws = get_workstation(db, tenant_id, workstation_pk)
    if installed_bundle_version is not None:
        ws.installed_bundle_version = installed_bundle_version
    if sync_status is not None:
        ws.last_sync_status = sync_status
    # Report the error verbatim (or clear it on a clean sync).
    ws.last_error = error
    if outbox_upload_status is not None:
        ws.outbox_upload_status = outbox_upload_status
    ws.last_seen_at = _utcnow()
    db.commit()
    db.refresh(ws)
    return ws
