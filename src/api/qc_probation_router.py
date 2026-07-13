"""API for Standard Probation (PRD Authoring Extension §3, WS7).

Exposes the read/report/pause/resume surface of
:mod:`src.qc_model.qualification.probation` over HTTP. ``start_probation`` and
``record_probation_job`` are deliberately NOT exposed as direct endpoints here
-- they are triggered by other server-side code paths (Bundle publish and the
human-final-decision path, respectively; see
``docs/api-contracts/probation-api.md`` §3), not called directly by Studio or
the Pad.

Note this is a *different* module from :mod:`src.api.qc_qualification_router`
/ :mod:`src.qc_model.qualification.service`, which implements the separate L3
accuracy-gate/shadow-mode qualification flow (PR 27).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.qualification import probation as service

router = APIRouter(prefix="/api/qc/probation", tags=["qc-probation"])


def _probation_view(p) -> dict:
    gate = service.evaluate_gate(p)
    return {
        "probation_id": p.id,
        "tenant_id": p.tenant_id,
        "sku_id": p.sku_id,
        "standard_revision_id": p.standard_revision_id,
        "status": p.status,
        "gate": gate.to_dict(),
    }


@router.get("/by-revision/{standard_revision_id}")
def get_by_revision(standard_revision_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    p = service.get_probation_for_revision(db, standard_revision_id, tenant_id)
    if p is None:
        raise HTTPException(status_code=404, detail="no probation record for this standard revision")
    return _probation_view(p)


@router.get("/{probation_id}")
def get_probation(probation_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        p = service.get_probation(db, probation_id, tenant_id)
    except service.ProbationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _probation_view(p)


@router.get("/{probation_id}/disagreement-report")
def get_disagreement_report(probation_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        return service.disagreement_report(db, probation_id, tenant_id)
    except service.ProbationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{probation_id}/pause")
def pause(probation_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        p = service.pause_probation(db, probation_id, tenant_id)
    except service.ProbationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidProbationState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _probation_view(p)


@router.post("/{probation_id}/resume")
def resume(probation_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        p = service.resume_probation(db, probation_id, tenant_id)
    except service.ProbationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidProbationState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _probation_view(p)
