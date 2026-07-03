"""FastAPI router for offline standard sync (Task 03).

Endpoints:
  POST /api/v1/qc/bundles/export            → build + sign a bundle, return metadata
  GET  /api/v1/qc/bundles/latest            → sync-window version check
  GET  /api/v1/qc/bundles/history           → bundle history (UI list)
  GET  /api/v1/qc/bundles/{id}/download     → download the signed archive
  GET  /api/v1/qc/bundles/public-key        → Ed25519 public key (Pad asset provisioning)
  POST /api/v1/qc/inspection-jobs/batch     → idempotent Pad→Server result upload (gen-3)

Auth per Task 02: tenant is derived from the caller's credential. Until Task 02
lands, tenant is taken from the request (the single seam `_resolve_tenant`).
"""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.sync import bundle_service, bundle_signing, result_ingest

router = APIRouter(prefix="/api/v1/qc", tags=["qc-offline-sync"])


def _resolve_tenant(tenant_id: str) -> str:
    # Task 02 seam: replace with credential-derived tenant when auth lands.
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")
    return tenant_id


# ── Bundle export / version check ─────────────────────────────────────────────


class ExportBundleRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    line_scope: str = ""
    sku_ids: Optional[List[str]] = None
    generated_by: Optional[str] = None


class BundleMetadata(BaseModel):
    id: str
    tenant_id: str
    line_scope: str
    bundle_version: int
    bundle_format_version: int
    sku_count: int
    archive_sha256: str
    manifest_sha256: str
    signing_key_fingerprint: str
    generated_at: str
    generated_by: Optional[str] = None
    downloaded_by: Optional[str] = None
    download_url: str


def _to_meta(rec) -> BundleMetadata:
    return BundleMetadata(
        id=rec.id,
        tenant_id=rec.tenant_id,
        line_scope=rec.line_scope,
        bundle_version=rec.bundle_version,
        bundle_format_version=rec.bundle_format_version,
        sku_count=rec.sku_count,
        archive_sha256=rec.archive_sha256,
        manifest_sha256=rec.manifest_sha256,
        signing_key_fingerprint=rec.signing_key_fingerprint,
        generated_at=rec.generated_at.isoformat(),
        generated_by=rec.generated_by,
        downloaded_by=rec.downloaded_by,
        download_url=f"/api/v1/qc/bundles/{rec.id}/download",
    )


@router.post("/bundles/export", status_code=201)
def export_bundle(body: ExportBundleRequest, db: Session = Depends(get_db_dep)) -> BundleMetadata:
    tenant = _resolve_tenant(body.tenant_id)
    try:
        exported = bundle_service.export_bundle(
            db,
            tenant_id=tenant,
            line_scope=body.line_scope,
            sku_filter=body.sku_ids,
            generated_by=body.generated_by,
        )
    except bundle_signing.SigningKeyError as exc:
        raise HTTPException(status_code=503, detail=f"signing unavailable: {exc}")
    except bundle_service.BundleExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_meta(exported.record)


@router.get("/bundles/latest")
def latest_bundle(
    tenant_id: str = Query(min_length=1),
    line_scope: str = Query(default=""),
    db: Session = Depends(get_db_dep),
) -> BundleMetadata:
    tenant = _resolve_tenant(tenant_id)
    rec = bundle_service.latest_bundle(db, tenant, line_scope)
    if rec is None:
        raise HTTPException(status_code=404, detail="no bundle exported for this tenant/line")
    return _to_meta(rec)


@router.get("/bundles/history")
def bundle_history(
    tenant_id: str = Query(min_length=1),
    line_scope: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db_dep),
) -> List[BundleMetadata]:
    from src.db.qc_bundle_models import QCStandardBundle

    tenant = _resolve_tenant(tenant_id)
    q = db.query(QCStandardBundle).filter(QCStandardBundle.tenant_id == tenant)
    if line_scope is not None:
        q = q.filter(QCStandardBundle.line_scope == line_scope)
    rows = q.order_by(QCStandardBundle.generated_at.desc()).limit(limit).all()
    return [_to_meta(r) for r in rows]


@router.get("/bundles/public-key")
def bundle_public_key() -> dict:
    try:
        signer = bundle_signing.load_signer()
    except bundle_signing.SigningKeyError as exc:
        raise HTTPException(status_code=503, detail=f"signing key unavailable: {exc}")
    return {
        "algorithm": "ed25519",
        "fingerprint": signer.fingerprint,
        "public_key_pem": signer.public_key_pem(),
        "public_key_b64_raw": signer.public_key_b64_raw(),
    }


@router.get("/bundles/{bundle_id}/download")
def download_bundle(
    bundle_id: str,
    tenant_id: str = Query(min_length=1),
    downloaded_by: Optional[str] = Query(default=None),
    db: Session = Depends(get_db_dep),
):
    from datetime import datetime, timezone

    from src.db.qc_bundle_models import QCStandardBundle

    tenant = _resolve_tenant(tenant_id)
    rec = db.query(QCStandardBundle).filter_by(id=bundle_id, tenant_id=tenant).first()
    if rec is None:
        raise HTTPException(status_code=404, detail="bundle not found")
    path = bundle_service._bundle_store_dir() / rec.archive_filename
    if not path.is_file():
        raise HTTPException(status_code=410, detail="bundle archive no longer on disk")
    rec.downloaded_by = downloaded_by or rec.downloaded_by
    rec.downloaded_at = datetime.now(timezone.utc)
    db.commit()
    return FileResponse(
        path=str(path),
        media_type="application/gzip",
        filename=rec.archive_filename,
    )


# ── Reverse sync: Pad → Server result upload ──────────────────────────────────


class BatchUploadRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    jobs: List[dict[str, Any]]


class JobUploadResult(BaseModel):
    job_uuid: str
    status: str
    reason: Optional[str] = None


class BatchUploadResponse(BaseModel):
    created: int
    duplicate: int
    rejected: int
    results: List[JobUploadResult]


@router.post("/inspection-jobs/batch")
def upload_job_batch(
    body: BatchUploadRequest, db: Session = Depends(get_db_dep),
) -> BatchUploadResponse:
    tenant = _resolve_tenant(body.tenant_id)
    outcomes = result_ingest.ingest_job_batch(db, tenant, body.jobs)
    counts = {"created": 0, "duplicate": 0, "rejected": 0}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
    return BatchUploadResponse(
        created=counts["created"],
        duplicate=counts["duplicate"],
        rejected=counts["rejected"],
        results=[JobUploadResult(job_uuid=o.job_uuid, status=o.status, reason=o.reason) for o in outcomes],
    )
