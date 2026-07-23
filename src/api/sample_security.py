"""Per-operation authorization for sample and standard mutations.

The signed admin session establishes identity. On top of that, the workflow
(2026-07-23 correction) is:

* 01 Sample & Standard entry (creating a sample, and any authoring/edits
  before it is first published) needs no extra credential -- it is normal
  admin work.
* Once a sample has been published at least once, it is a live production
  standard: any further operation on it (new photo, edit, archive,
  re-publish, ...) requires a second credential, distinct from the login
  password/API key and never stored in the session.
* Formal publication itself always requires the credential, including the
  very first publish.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.admin_auth import current_admin
from src.api.deps import get_db_dep
from src.db.intake_models import QCStandardIntake
from src.db.pad_models import QCOperatorProfile
from src.db.sku_models import QCDetectionPoint
from src.db.studio_models import QCPublishBundle
from src.pad.session_service import _verify_password

MUTATION_HEADER = "X-QC-Mutation-Key"
SAMPLE_SURFACE_HEADER = "X-QC-Sample-Surface"
SAMPLE_SURFACE_VALUE = "sample-standard"
TEST_MUTATION_KEY = "sample-mutation-test-key"


def _configured_credential() -> tuple[str, str]:
    credential_hash = os.getenv("QC_SAMPLE_MUTATION_KEY_HASH", "").strip()
    if credential_hash:
        return "hash", credential_hash
    credential = os.getenv("QC_SAMPLE_MUTATION_KEY", "").strip()
    if not credential and os.getenv("APP_ENV", "production").lower() == "test":
        credential = TEST_MUTATION_KEY
    if not credential:
        raise HTTPException(status_code=503, detail="Sample mutation authorization is not configured")
    if len(credential) < 12:
        raise HTTPException(status_code=503, detail="Sample mutation authorization is misconfigured")
    return "plain", credential


def _matches_configured(credential: str) -> bool:
    mode, configured = _configured_credential()
    if mode == "hash":
        return _verify_password(credential, configured)
    return hmac.compare_digest(credential.encode("utf-8"), configured.encode("utf-8"))


def _request_login_credential(request: Request) -> Optional[str]:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key.strip()
    authorization = request.headers.get("Authorization", "").strip()
    if authorization and " " in authorization:
        return authorization.split(" ", 1)[1].strip()
    return None


def verify_sample_mutation_credential(
    request: Request,
    db: Session,
    credential: Optional[str] = None,
) -> None:
    """Validate a one-operation credential and enforce credential separation."""
    supplied = (credential or request.headers.get(MUTATION_HEADER) or "").strip()
    if not supplied or not _matches_configured(supplied):
        raise HTTPException(status_code=403, detail="Valid sample mutation authorization is required")

    admin = current_admin(request)
    if admin is not None:
        profile = db.query(QCOperatorProfile).filter_by(
            id=admin.operator_id, tenant_id=admin.tenant_id
        ).first()
        if profile is not None and _verify_password(supplied, profile.password_hash):
            raise HTTPException(
                status_code=400,
                detail="Sample mutation credential must differ from the login credential",
            )
    login_credential = _request_login_credential(request)
    if login_credential and hmac.compare_digest(
        supplied.encode("utf-8"), login_credential.encode("utf-8")
    ):
        raise HTTPException(
            status_code=400,
            detail="Sample mutation credential must differ from the login credential",
        )


def sample_is_published(db: Session, sku_id: Optional[str], tenant_id: str) -> bool:
    """Has this SKU ever gone through formal publish (has a signed bundle)?

    Pre-publish, a sample is still being entered/authored -- no extra
    credential required. Post-publish, it is a live production standard.
    """
    if not sku_id:
        return False
    return (
        db.query(QCPublishBundle)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id)
        .first()
        is not None
    )


async def _read_body(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return await request.json()
        except Exception:
            return {}
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        return dict(await request.form())
    return {}


async def _resolve_target_sku(request: Request, db: Session) -> tuple[Optional[str], str]:
    """Best-effort resolve which sample a mutation targets, for the
    entry-vs-published-sample boundary. Returns (sku_id or None, tenant_id)."""
    body = await _read_body(request)
    tenant_id = str(body.get("tenant_id") or "default")

    sku_id = request.path_params.get("sku_id") or body.get("sku_id")
    if sku_id:
        return str(sku_id), tenant_id

    detection_point_id = request.path_params.get("detection_point_id")
    if detection_point_id:
        dp = db.query(QCDetectionPoint).filter_by(id=detection_point_id).first()
        if dp is not None:
            return dp.sku_id, dp.tenant_id

    intake_id = body.get("intake_id")
    if intake_id:
        intake = db.query(QCStandardIntake).filter_by(id=intake_id).first()
        if intake is not None:
            return intake.sku_id, intake.tenant_id

    return None, tenant_id


async def require_sample_admin_mutation(
    request: Request,
    db: Session = Depends(get_db_dep),
) -> None:
    """Router dependency: protect every /admin/samples operation on an
    already-published sample. Entry (create) and pre-publish authoring/edits
    need no extra credential."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    sku_id = request.path_params.get("sku_id")
    if sku_id is None:
        # POST /admin/samples -- creating a new sample is entry itself.
        return
    form = await request.form()
    tenant_id = str(form.get("tenant_id") or "default")
    if not sample_is_published(db, sku_id, tenant_id):
        return
    verify_sample_mutation_credential(
        request, db, str(form.get("mutation_credential") or "")
    )


async def require_sample_surface_mutation(
    request: Request,
    db: Session = Depends(get_db_dep),
) -> None:
    """Router dependency: protect /admin/studio sample-authoring endpoints.

    The Sample & Standard surface restriction always applies (Digital QC
    Studio must never author or edit samples). The extra credential is only
    required once the targeted sample has been published at least once --
    entry and pre-publish authoring do not need it.
    """
    if request.headers.get(SAMPLE_SURFACE_HEADER) != SAMPLE_SURFACE_VALUE:
        raise HTTPException(status_code=403, detail="Sample changes are only allowed from Sample & Standard")
    sku_id, tenant_id = await _resolve_target_sku(request, db)
    if not sample_is_published(db, sku_id, tenant_id):
        return
    verify_sample_mutation_credential(request, db)


__all__ = [
    "MUTATION_HEADER",
    "SAMPLE_SURFACE_HEADER",
    "SAMPLE_SURFACE_VALUE",
    "TEST_MUTATION_KEY",
    "require_sample_admin_mutation",
    "require_sample_surface_mutation",
    "verify_sample_mutation_credential",
]
