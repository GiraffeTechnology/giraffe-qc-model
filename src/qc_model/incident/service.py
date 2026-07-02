"""False-pass incident response & requalification loop service (PR 28).

Closes the production safety loop:
  report → (supervisor) confirm → suspend L3 scope + require requalification
  → new approved passing qualification → supervisor lifts suspension → L3 restorable.

Invariants:
- False pass is P0.
- A confirmed false pass suspends ``controlled_active`` for the affected scope
  and requires a new supervisor-approved, threshold-meeting, production-eligible
  qualification report created *after* the confirmation before L3 can be
  restored. L2 ``production_assisted`` stays available.
- Prior approved qualification reports are never mutated/deleted.
- Every state change appends an immutable audit event.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.qc_incident_models import (
    CONFIRM_FALSE_PASS,
    CONFIRM_NEEDS_EVIDENCE,
    CONFIRM_REJECTED,
    DEFAULT_SEVERITY,
    INCIDENT_FALSE_PASS,
    L3_BLOCKING_SUSPENSION_TYPES,
    REQUAL_REQUIRED,
    REQUAL_SATISFIED,
    STATUS_CONFIRMED,
    STATUS_REJECTED,
    STATUS_REQUAL_REQUIRED,
    STATUS_TRIAGE_PENDING,
    SUSP_ACTIVE,
    SUSP_CONTROLLED_ACTIVE_SUSPENDED,
    SUSP_LIFTED,
    VALID_CONFIRMATION_DECISIONS,
    VALID_INCIDENT_TYPES,
    QCIncidentAuditEvent,
    QCQualityIncident,
    QCRequalificationRequirement,
    QCScopeSuspension,
)
from src.db.qc_qualification_models import QualificationReport, QualificationRun, REPORT_APPROVED
from src.qc_model.production.provider import is_production_eligible_provider
from src.qc_model.training_pack.ownership import assert_pack_accessible


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class IncidentNotFound(ValueError):
    pass


class SuspensionNotFound(ValueError):
    pass


class InvalidIncident(ValueError):
    pass


class InvalidConfirmation(ValueError):
    pass


class InvalidLift(ValueError):
    pass


# ── Audit ────────────────────────────────────────────────────────────────────


def _audit(db, tenant_id, event_type, *, incident_id=None, suspension_id=None,
           requalification_requirement_id=None, actor_id=None, actor_role=None, payload=None):
    db.add(QCIncidentAuditEvent(
        id=_uid(), tenant_id=tenant_id, incident_id=incident_id, suspension_id=suspension_id,
        requalification_requirement_id=requalification_requirement_id, event_type=event_type,
        actor_id=actor_id, actor_role=actor_role, event_payload_json=payload or {},
    ))


def list_audit_events(db: Session, incident_id: str, tenant_id: str = "default") -> list[QCIncidentAuditEvent]:
    return (
        db.query(QCIncidentAuditEvent)
        .filter_by(incident_id=incident_id, tenant_id=tenant_id)
        .order_by(QCIncidentAuditEvent.created_at.asc())
        .all()
    )


# ── Report ───────────────────────────────────────────────────────────────────


def report_incident(
    db: Session, training_pack_id: str, incident_type: str = INCIDENT_FALSE_PASS,
    tenant_id: str = "default", *, sku_id=None, station_id=None, detection_point_code=None,
    provider=None, model=None, inspection_session_id=None, inspection_run_id=None,
    production_detection_result_id=None, qualification_run_id=None, qualification_report_id=None,
    shadow_observation_id=None, reported_by=None, reported_role=None, report_source=None,
    description=None, evidence_refs=None, model_output=None, human_or_downstream_decision=None,
) -> QCQualityIncident:
    if incident_type not in VALID_INCIDENT_TYPES:
        raise InvalidIncident(f"invalid incident_type: {incident_type!r}")
    # Fail closed: scope must be at least tenant + training_pack.
    if not training_pack_id:
        raise InvalidIncident("training_pack_id is required to scope an incident")
    assert_pack_accessible(db, training_pack_id, tenant_id)

    affected_scope = _resolve_scope(tenant_id, training_pack_id, sku_id, station_id,
                                    detection_point_code, provider, model)
    incident = QCQualityIncident(
        id=_uid(), tenant_id=tenant_id, incident_type=incident_type,
        severity=DEFAULT_SEVERITY.get(incident_type, "P1"), status=STATUS_TRIAGE_PENDING,
        training_pack_id=training_pack_id, sku_id=sku_id, station_id=station_id,
        detection_point_code=detection_point_code, provider=provider, model=model,
        inspection_session_id=inspection_session_id, inspection_run_id=inspection_run_id,
        production_detection_result_id=production_detection_result_id,
        qualification_run_id=qualification_run_id, qualification_report_id=qualification_report_id,
        shadow_observation_id=shadow_observation_id, reported_by=reported_by, reported_role=reported_role,
        report_source=report_source, description=description, evidence_refs_json=evidence_refs or [],
        model_output_json=model_output or {}, human_or_downstream_decision_json=human_or_downstream_decision or {},
        affected_scope_json=affected_scope,
    )
    db.add(incident)
    db.flush()
    _audit(db, tenant_id, "incident_reported", incident_id=incident.id,
           actor_id=reported_by, actor_role=reported_role,
           payload={"incident_type": incident_type, "severity": incident.severity, "scope": affected_scope})
    db.commit()
    db.refresh(incident)
    return incident


def _resolve_scope(tenant_id, training_pack_id, sku_id, station_id, detection_point_code, provider, model) -> dict:
    scope = {"tenant_id": tenant_id, "training_pack_id": training_pack_id}
    for key, val in (("sku_id", sku_id), ("station_id", station_id),
                     ("detection_point_code", detection_point_code),
                     ("provider", provider), ("model", model)):
        if val:
            scope[key] = val
    # Ambiguous scope (no sku/station/detection point) → broader pack-level scope.
    scope["granularity"] = "detection_point" if detection_point_code else (
        "station" if station_id else "training_pack")
    return scope


def get_incident(db: Session, incident_id: str, tenant_id: str = "default") -> QCQualityIncident:
    inc = db.query(QCQualityIncident).filter_by(id=incident_id, tenant_id=tenant_id).first()
    if inc is None:
        raise IncidentNotFound(f"Incident {incident_id!r} not found")
    return inc


def get_incident_bundle(db: Session, incident_id: str, tenant_id: str = "default") -> dict:
    inc = get_incident(db, incident_id, tenant_id)
    suspensions = db.query(QCScopeSuspension).filter_by(incident_id=inc.id, tenant_id=tenant_id).all()
    requals = db.query(QCRequalificationRequirement).filter_by(incident_id=inc.id, tenant_id=tenant_id).all()
    return {
        "incident": inc,
        "suspensions": suspensions,
        "requalification_requirements": requals,
        "audit_events": list_audit_events(db, inc.id, tenant_id),
    }


# ── Confirm ──────────────────────────────────────────────────────────────────


def confirm_incident(
    db: Session, incident_id: str, confirmation_decision: str, confirmed_by: str,
    tenant_id: str = "default", confirmation_role: str = "supervisor", confirmation_reason: str = "",
    evidence_refs: Optional[list] = None,
) -> QCQualityIncident:
    inc = get_incident(db, incident_id, tenant_id)
    if confirmation_decision not in VALID_CONFIRMATION_DECISIONS:
        raise InvalidConfirmation(f"invalid confirmation_decision: {confirmation_decision!r}")
    if not confirmed_by or not confirmed_by.strip():
        raise InvalidConfirmation("confirmation requires a supervisor identity")
    if confirmation_decision in (CONFIRM_FALSE_PASS, CONFIRM_REJECTED) and not (confirmation_reason or "").strip():
        raise InvalidConfirmation("confirmation requires a reason")

    payload = {"decision": confirmation_decision, "reason": confirmation_reason,
               "role": confirmation_role, "evidence_refs": evidence_refs or []}

    if confirmation_decision == CONFIRM_NEEDS_EVIDENCE:
        inc.status = STATUS_TRIAGE_PENDING
        _audit(db, tenant_id, "incident_triaged", incident_id=inc.id, actor_id=confirmed_by,
               actor_role=confirmation_role, payload=payload)
        db.commit()
        db.refresh(inc)
        return inc

    if confirmation_decision == CONFIRM_REJECTED:
        inc.status = STATUS_REJECTED
        _audit(db, tenant_id, "incident_rejected", incident_id=inc.id, actor_id=confirmed_by,
               actor_role=confirmation_role, payload=payload)
        db.commit()
        db.refresh(inc)
        return inc

    # confirmed_false_pass → suspend + require requalification.
    inc.status = STATUS_CONFIRMED
    inc.confirmed_by = confirmed_by
    inc.confirmed_at = _now()
    _audit(db, tenant_id, "incident_confirmed", incident_id=inc.id, actor_id=confirmed_by,
           actor_role=confirmation_role, payload=payload)

    suspension = QCScopeSuspension(
        id=_uid(), tenant_id=tenant_id, incident_id=inc.id, training_pack_id=inc.training_pack_id,
        sku_id=inc.sku_id, station_id=inc.station_id, detection_point_code=inc.detection_point_code,
        provider=inc.provider, model=inc.model, scope_json=inc.affected_scope_json,
        suspension_type=SUSP_CONTROLLED_ACTIVE_SUSPENDED, status=SUSP_ACTIVE,
        reason=f"confirmed false pass (incident {inc.id})", created_by=confirmed_by,
    )
    db.add(suspension)
    db.flush()
    _audit(db, tenant_id, "suspension_created", incident_id=inc.id, suspension_id=suspension.id,
           actor_id=confirmed_by, actor_role=confirmation_role,
           payload={"suspension_type": suspension.suspension_type, "scope": suspension.scope_json})

    prev_report = _latest_approved_report_before(db, inc.training_pack_id, tenant_id, inc.confirmed_at)
    requal = QCRequalificationRequirement(
        id=_uid(), tenant_id=tenant_id, incident_id=inc.id, suspension_id=suspension.id,
        training_pack_id=inc.training_pack_id, sku_id=inc.sku_id, station_id=inc.station_id,
        detection_point_code=inc.detection_point_code,
        previous_qualification_report_id=prev_report.id if prev_report else None,
        required_reason="requalification required after confirmed false pass",
        required_scope_json=inc.affected_scope_json, status=REQUAL_REQUIRED, created_by=confirmed_by,
    )
    db.add(requal)
    db.flush()
    _audit(db, tenant_id, "requalification_required", incident_id=inc.id, suspension_id=suspension.id,
           requalification_requirement_id=requal.id, actor_id=confirmed_by, actor_role=confirmation_role,
           payload={"previous_qualification_report_id": requal.previous_qualification_report_id})

    inc.status = STATUS_REQUAL_REQUIRED
    db.commit()
    db.refresh(inc)
    return inc


def _latest_approved_report_before(db, training_pack_id, tenant_id, before) -> Optional[QualificationReport]:
    reports = (
        db.query(QualificationReport)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id, status=REPORT_APPROVED)
        .all()
    )
    candidates = [r for r in reports if before is None or _as_utc(r.created_at) <= _as_utc(before)]
    candidates.sort(key=lambda r: _as_utc(r.created_at), reverse=True)
    return candidates[0] if candidates else None


# ── Suspensions ──────────────────────────────────────────────────────────────


def get_suspension(db: Session, suspension_id: str, tenant_id: str = "default") -> QCScopeSuspension:
    s = db.query(QCScopeSuspension).filter_by(id=suspension_id, tenant_id=tenant_id).first()
    if s is None:
        raise SuspensionNotFound(f"Suspension {suspension_id!r} not found")
    return s


def list_suspensions(db: Session, tenant_id: str = "default", training_pack_id: Optional[str] = None,
                     active_only: bool = True) -> list[QCScopeSuspension]:
    q = db.query(QCScopeSuspension).filter_by(tenant_id=tenant_id)
    if training_pack_id:
        q = q.filter_by(training_pack_id=training_pack_id)
    if active_only:
        q = q.filter_by(status=SUSP_ACTIVE)
    return q.order_by(QCScopeSuspension.created_at.desc()).all()


def active_l3_suspensions_for_pack(db: Session, training_pack_id: str, tenant_id: str = "default") -> list[QCScopeSuspension]:
    """Active suspensions that block L3 controlled_active for this pack."""
    return [
        s for s in list_suspensions(db, tenant_id, training_pack_id, active_only=True)
        if s.suspension_type in L3_BLOCKING_SUSPENSION_TYPES
    ]


def lift_suspension(
    db: Session, suspension_id: str, lifted_by: str, requalification_report_id: str,
    tenant_id: str = "default", lift_role: str = "supervisor", lift_reason: str = "",
) -> QCScopeSuspension:
    suspension = get_suspension(db, suspension_id, tenant_id)
    if suspension.status != SUSP_ACTIVE:
        raise InvalidLift(f"suspension {suspension_id!r} is not active (status={suspension.status})")
    if not lifted_by or not lifted_by.strip():
        raise InvalidLift("lifting a suspension requires an identity")
    if not (lift_reason or "").strip():
        raise InvalidLift("lifting a suspension requires a reason")
    if not requalification_report_id:
        raise InvalidLift("a valid requalification_report_id is required to lift a false-pass suspension")

    report = db.query(QualificationReport).filter_by(id=requalification_report_id, tenant_id=tenant_id).first()
    incident = get_incident(db, suspension.incident_id, tenant_id)
    _validate_requalification_report(db, report, suspension, incident, tenant_id)

    suspension.status = SUSP_LIFTED
    suspension.lifted_by = lifted_by
    suspension.lifted_at = _now()
    suspension.lift_reason = lift_reason
    suspension.requalification_report_id = report.id

    # Satisfy the linked requalification requirement(s).
    requals = db.query(QCRequalificationRequirement).filter_by(
        suspension_id=suspension.id, tenant_id=tenant_id).all()
    for requal in requals:
        requal.status = REQUAL_SATISFIED
        requal.satisfied_by_report_id = report.id
        requal.satisfied_by = lifted_by
        requal.satisfied_at = _now()
        _audit(db, tenant_id, "requalification_satisfied", incident_id=incident.id,
               suspension_id=suspension.id, requalification_requirement_id=requal.id,
               actor_id=lifted_by, actor_role=lift_role, payload={"report_id": report.id})

    _audit(db, tenant_id, "suspension_lifted", incident_id=incident.id, suspension_id=suspension.id,
           actor_id=lifted_by, actor_role=lift_role,
           payload={"requalification_report_id": report.id, "reason": lift_reason})
    db.commit()
    db.refresh(suspension)
    return suspension


def _validate_requalification_report(db, report, suspension, incident, tenant_id) -> None:
    if report is None:
        raise InvalidLift("requalification report not found for this tenant")
    if report.training_pack_id != suspension.training_pack_id:
        raise InvalidLift("requalification report is for a different training pack")
    if report.status != REPORT_APPROVED:
        raise InvalidLift("requalification report is not supervisor-approved")
    if not report.overall_meets_thresholds:
        raise InvalidLift("requalification report does not meet thresholds (false pass still present)")
    # Must be created after the incident confirmation — an old report cannot restore L3.
    if incident.confirmed_at is not None and _as_utc(report.created_at) <= _as_utc(incident.confirmed_at):
        raise InvalidLift("requalification report predates the incident confirmation")
    # The qualifying run must use a production-eligible provider (no mock restore).
    run = db.query(QualificationRun).filter_by(id=report.run_id, tenant_id=tenant_id).first()
    if run is None or not is_production_eligible_provider(run.provider):
        raise InvalidLift("requalification report was not produced by a production-eligible provider")
