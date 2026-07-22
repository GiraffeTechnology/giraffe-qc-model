"""Per-operation authorization for sample and standard mutations.

The signed admin session establishes identity, but sample changes and formal
publication require a second credential on every operation.  The credential
is never stored in the session and must differ from the active login password
or API key.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.admin_auth import current_admin
from src.api.deps import get_db_dep
from src.db.pad_models import QCOperatorProfile
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
    *,
    require_sample_surface: bool = False,
) -> None:
    """Validate a one-operation credential and enforce credential separation."""
    if require_sample_surface and request.headers.get(SAMPLE_SURFACE_HEADER) != SAMPLE_SURFACE_VALUE:
        raise HTTPException(status_code=403, detail="Sample changes are only allowed from Sample & Standard")
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


async def require_sample_admin_mutation(
    request: Request,
    db: Session = Depends(get_db_dep),
) -> None:
    """Router dependency: protect every non-read operation under /admin/samples."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    form = await request.form()
    verify_sample_mutation_credential(
        request, db, str(form.get("mutation_credential") or "")
    )


def require_sample_surface_mutation(
    request: Request,
    db: Session = Depends(get_db_dep),
) -> None:
    verify_sample_mutation_credential(request, db, require_sample_surface=True)


__all__ = [
    "MUTATION_HEADER",
    "SAMPLE_SURFACE_HEADER",
    "SAMPLE_SURFACE_VALUE",
    "TEST_MUTATION_KEY",
    "require_sample_admin_mutation",
    "require_sample_surface_mutation",
    "verify_sample_mutation_credential",
]
