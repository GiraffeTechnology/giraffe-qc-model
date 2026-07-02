"""SQLAlchemy models for false-pass incident response & requalification (PR 28).

Closes the production safety loop: a confirmed false pass is a P0 incident that
suspends L3 ``controlled_active`` for the affected scope and requires a new
supervisor-approved, threshold-meeting qualification report before L3 can be
restored. L2 ``production_assisted`` (human-final) remains available.

Safety invariants:
- Every entity is tenant-scoped.
- ``QCIncidentAuditEvent`` is append-only (no update/delete API).
- Prior approved qualification reports are never mutated/deleted; invalidation is
  expressed via an append-only requalification requirement + a suspension.
- False pass is P0.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow

# Incident types.
INCIDENT_FALSE_PASS = "false_pass"
INCIDENT_FALSE_FAIL = "false_fail"
INCIDENT_PROVIDER_FAILURE = "provider_failure"
INCIDENT_READINESS_BYPASS = "readiness_bypass_attempt"
INCIDENT_MANUAL_QUALITY_ESCAPE = "manual_quality_escape"
VALID_INCIDENT_TYPES = {
    INCIDENT_FALSE_PASS, INCIDENT_FALSE_FAIL, INCIDENT_PROVIDER_FAILURE,
    INCIDENT_READINESS_BYPASS, INCIDENT_MANUAL_QUALITY_ESCAPE,
}
DEFAULT_SEVERITY = {
    INCIDENT_FALSE_PASS: "P0",
    INCIDENT_FALSE_FAIL: "P2",
    INCIDENT_PROVIDER_FAILURE: "P1",
    INCIDENT_READINESS_BYPASS: "P0",
    INCIDENT_MANUAL_QUALITY_ESCAPE: "P0",
}

# Incident status.
STATUS_REPORTED = "reported"
STATUS_TRIAGE_PENDING = "triage_pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_SCOPE_SUSPENDED = "scope_suspended"
STATUS_REQUAL_REQUIRED = "requalification_required"
STATUS_REQUAL_IN_PROGRESS = "requalification_in_progress"
STATUS_RESOLVED = "resolved"
STATUS_CLOSED = "closed"

# Confirmation decisions.
CONFIRM_FALSE_PASS = "confirmed_false_pass"
CONFIRM_REJECTED = "rejected_not_false_pass"
CONFIRM_NEEDS_EVIDENCE = "needs_more_evidence"
VALID_CONFIRMATION_DECISIONS = {CONFIRM_FALSE_PASS, CONFIRM_REJECTED, CONFIRM_NEEDS_EVIDENCE}

# Suspension types.
SUSP_CONTROLLED_ACTIVE_SUSPENDED = "controlled_active_suspended"
SUSP_CONTROLLED_ACTIVE_DOWNGRADED = "controlled_active_downgraded_to_l2"
SUSP_PROVIDER_SUSPENDED = "provider_suspended"
SUSP_STATION_SUSPENDED = "station_suspended"
SUSP_TRAINING_PACK_SUSPENDED = "training_pack_suspended"
# Suspension types that block L3 controlled_active at pack level.
L3_BLOCKING_SUSPENSION_TYPES = {
    SUSP_CONTROLLED_ACTIVE_SUSPENDED, SUSP_CONTROLLED_ACTIVE_DOWNGRADED,
    SUSP_STATION_SUSPENDED, SUSP_TRAINING_PACK_SUSPENDED, SUSP_PROVIDER_SUSPENDED,
}

# Suspension status.
SUSP_ACTIVE = "active"
SUSP_LIFT_PENDING = "lift_pending_requalification"
SUSP_LIFTED = "lifted"
SUSP_EXPIRED = "expired"

# Requalification requirement status.
REQUAL_REQUIRED = "required"
REQUAL_IN_PROGRESS = "in_progress"
REQUAL_SATISFIED = "satisfied"
REQUAL_CANCELLED = "cancelled"


class QCQualityIncident(Base):
    __tablename__ = "qc_quality_incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    incident_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default="P0")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default=STATUS_TRIAGE_PENDING, index=True)
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    station_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    inspection_session_id: Mapped[Optional[str]] = mapped_column(String(64))
    inspection_run_id: Mapped[Optional[str]] = mapped_column(String(64))
    production_detection_result_id: Mapped[Optional[str]] = mapped_column(String(64))
    qualification_run_id: Mapped[Optional[str]] = mapped_column(String(64))
    qualification_report_id: Mapped[Optional[str]] = mapped_column(String(64))
    shadow_observation_id: Mapped[Optional[str]] = mapped_column(String(64))
    reported_by: Mapped[Optional[str]] = mapped_column(String(128))
    reported_role: Mapped[Optional[str]] = mapped_column(String(64))
    report_source: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)
    evidence_refs_json: Mapped[Optional[list]] = mapped_column(JSON)
    model_output_json: Mapped[Optional[dict]] = mapped_column(JSON)
    human_or_downstream_decision_json: Mapped[Optional[dict]] = mapped_column(JSON)
    affected_scope_json: Mapped[Optional[dict]] = mapped_column(JSON)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(128))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class QCScopeSuspension(Base):
    __tablename__ = "qc_scope_suspensions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    station_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    scope_json: Mapped[Optional[dict]] = mapped_column(JSON)
    suspension_type: Mapped[str] = mapped_column(String(48), nullable=False, default=SUSP_CONTROLLED_ACTIVE_SUSPENDED)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default=SUSP_ACTIVE, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    lifted_by: Mapped[Optional[str]] = mapped_column(String(128))
    lifted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    lift_reason: Mapped[Optional[str]] = mapped_column(Text)
    requalification_report_id: Mapped[Optional[str]] = mapped_column(String(64))


class QCRequalificationRequirement(Base):
    __tablename__ = "qc_requalification_requirements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    suspension_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[Optional[str]] = mapped_column(String(64))
    station_id: Mapped[Optional[str]] = mapped_column(String(64))
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64))
    previous_qualification_report_id: Mapped[Optional[str]] = mapped_column(String(64))
    required_reason: Mapped[Optional[str]] = mapped_column(Text)
    required_scope_json: Mapped[Optional[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=REQUAL_REQUIRED, index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    satisfied_by_report_id: Mapped[Optional[str]] = mapped_column(String(64))
    satisfied_by: Mapped[Optional[str]] = mapped_column(String(128))
    satisfied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class QCIncidentAuditEvent(Base):
    """Append-only audit event for the incident/suspension/requalification loop."""

    __tablename__ = "qc_incident_audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    incident_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    suspension_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    requalification_requirement_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(128))
    actor_role: Mapped[Optional[str]] = mapped_column(String(64))
    event_payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
