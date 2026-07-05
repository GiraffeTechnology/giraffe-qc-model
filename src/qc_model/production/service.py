"""Production Assisted Mode service (PR 25).

Session → capture → run (confirmed detection points only) → recommended
disposition + evidence → mandatory human final decision (append-only audit).

Hard rules enforced here:
- A session can only start when the pack passes ``production_assisted`` readiness.
- A run refuses to use a non-production-eligible provider (mock/fake/stub/
  skeleton/deterministic) — fail closed.
- The run only produces *recommended* dispositions; it never finalizes.
- Physical-measurement points return ``measurement_required`` (never AI pass).
- Missing required evidence downgrades a pass to ``review_required``.
- The final pass/reject/review decision requires a human identity and is
  appended to an immutable audit trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal, QCLearningJob
from src.db.qc_production_models import (
    DISPOSITION_CAPTURE_RETRY,
    DISPOSITION_MEASUREMENT,
    DISPOSITION_PASS,
    DISPOSITION_REJECT,
    DISPOSITION_REVIEW,
    HumanFinalDecision,
    PRODUCTION_MODE_ASSISTED,
    ProductionCapture,
    ProductionDetectionResult,
    ProductionEvidencePacket,
    ProductionInspectionRun,
    ProductionInspectionSession,
    VALID_FINAL_DECISIONS,
)
from src.db.qc_sample_learning_models import QCConfirmedVisualRule
from src.qc_model.production.provider import (
    PROMPT_SCHEMA_VERSION,
    DetectionInspectionRequest,
    ProductionInspectionProvider,
    ProductionProviderError,
    ProductionProviderNotConfigured,
    ProductionProviderSchemaError,
    get_production_inspection_provider,
    is_production_eligible_provider,
)
from src.qc_model.production.runtime import (
    assert_server_side_runtime,
)
from src.qc_model.readiness.evaluator import TARGET_PRODUCTION_ASSISTED, evaluate_readiness
from src.qc_model.training_pack.ownership import assert_pack_accessible


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionNotFound(ValueError):
    pass


class RunNotFound(ValueError):
    pass


class ReadinessNotMet(ValueError):
    """The pack is not production_assisted-ready."""


class ProviderNotEligible(ValueError):
    """Configured inspection provider is not production-eligible."""


class NoCaptures(ValueError):
    pass


class InvalidFinalDecision(ValueError):
    pass


class ProviderInspectionFailed(ValueError):
    def __init__(self, message: str, schema_error: bool = False):
        super().__init__(message)
        self.schema_error = schema_error


# ── Sessions ───────────────────────────────────────────────────────────────


def create_session(
    db: Session,
    training_pack_id: str,
    tenant_id: str = "default",
    sku_id: Optional[str] = None,
    station_id: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> ProductionInspectionSession:
    """Start a production-assisted session, gated on L2 readiness."""
    assert_pack_accessible(db, training_pack_id, tenant_id)
    readiness = evaluate_readiness(db, training_pack_id, tenant_id, target_mode=TARGET_PRODUCTION_ASSISTED)
    if not readiness.production_assisted_allowed:
        raise ReadinessNotMet(
            "training pack is not production_assisted-ready: "
            + ", ".join(readiness.to_dict()["blocking_checks"])
        )
    session = ProductionInspectionSession(
        id=_uid(), tenant_id=tenant_id, training_pack_id=training_pack_id,
        sku_id=sku_id, station_id=station_id, operator_id=operator_id,
        production_mode=PRODUCTION_MODE_ASSISTED, status="open",
        readiness_snapshot_json=readiness.to_dict(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str, tenant_id: str = "default") -> ProductionInspectionSession:
    s = db.query(ProductionInspectionSession).filter_by(id=session_id, tenant_id=tenant_id).first()
    if s is None:
        raise SessionNotFound(f"Production session {session_id!r} not found")
    return s


def add_capture(
    db: Session,
    session_id: str,
    image_reference: str,
    tenant_id: str = "default",
    capture_metadata: Optional[dict] = None,
) -> ProductionCapture:
    session = get_session(db, session_id, tenant_id)
    capture = ProductionCapture(
        id=_uid(), tenant_id=tenant_id, session_id=session.id,
        training_pack_id=session.training_pack_id,
        image_reference=image_reference, capture_metadata_json=capture_metadata or {},
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)
    return capture


def list_captures(db: Session, session_id: str, tenant_id: str = "default") -> list[ProductionCapture]:
    get_session(db, session_id, tenant_id)
    return (
        db.query(ProductionCapture)
        .filter_by(session_id=session_id, tenant_id=tenant_id)
        .order_by(ProductionCapture.created_at.asc())
        .all()
    )


# ── Confirmed detection points ───────────────────────────────────────────────


def _pack_proposals(db: Session, training_pack_id: str, tenant_id: str):
    learning_ids = [
        r[0] for r in db.query(QCLearningJob.id).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    ]
    authoring_ids = [
        r[0] for r in db.query(RuleAuthoringJob.id).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    ]
    proposals = db.query(QCLearnedDetectionPointProposal).filter_by(tenant_id=tenant_id).all()
    return [
        p for p in proposals
        if (p.learning_job_id in learning_ids) or (p.rule_authoring_job_id in authoring_ids)
    ]


# ── Run inspection ───────────────────────────────────────────────────────────


def run_inspection(
    db: Session,
    session_id: str,
    tenant_id: str = "default",
    provider: Optional[ProductionInspectionProvider] = None,
) -> ProductionInspectionRun:
    session = get_session(db, session_id, tenant_id)

    # Production runs are server-side only; tablet_mnn is refused (§ PR 26).
    assert_server_side_runtime()

    # Readiness must still hold at run time.
    readiness = evaluate_readiness(db, session.training_pack_id, tenant_id, target_mode=TARGET_PRODUCTION_ASSISTED)
    if not readiness.production_assisted_allowed:
        raise ReadinessNotMet("training pack is no longer production_assisted-ready")

    # Resolve the configured provider. The real server VLM path never falls back
    # to mock; an unconfigured real provider fails closed.
    provider = provider or get_production_inspection_provider()
    if not getattr(provider, "is_configured", True):
        raise ProductionProviderNotConfigured("production_provider_not_configured")
    # Fail closed: never run a production inspection on a non-eligible provider.
    if not getattr(provider, "production_eligible", False) or not is_production_eligible_provider(provider.provider_name):
        raise ProviderNotEligible(
            f"provider {provider.provider_name!r} is not production-eligible; "
            "mock/fake/stub/skeleton/deterministic providers can serve L0 only"
        )

    captures = list_captures(db, session_id, tenant_id)
    if not captures:
        raise NoCaptures("at least one capture is required before running a production inspection")
    image_refs = [c.image_reference for c in captures]
    capture_metadata = captures[0].capture_metadata_json or {}

    run = ProductionInspectionRun(
        id=_uid(), tenant_id=tenant_id, session_id=session.id,
        training_pack_id=session.training_pack_id,
        provider=provider.provider_name, model=provider.model_name,
        prompt_schema_version=PROMPT_SCHEMA_VERSION, status="running",
    )
    db.add(run)
    db.commit()

    confirmed_rules = (
        db.query(QCConfirmedVisualRule)
        .filter_by(training_pack_id=session.training_pack_id, tenant_id=tenant_id)
        .all()
    )
    physical_points = [
        p for p in _pack_proposals(db, session.training_pack_id, tenant_id)
        if p.proposed_checkpoint_category == "physical_measurement"
        and p.status in ("approved", "applied")
    ]

    results: list[ProductionDetectionResult] = []
    try:
        for rule in confirmed_rules:
            content = rule.content_json or {}
            request = DetectionInspectionRequest(
                detection_point_code=rule.detection_point_code or "",
                checkpoint_category="visual",
                confirmed_content=content,
                image_references=image_refs,
                capture_metadata=capture_metadata,
            )
            try:
                response = provider.inspect(request)
            except ProductionProviderSchemaError as exc:
                raise ProviderInspectionFailed(str(exc), schema_error=True) from exc
            except (ProductionProviderError, ProductionProviderNotConfigured) as exc:
                raise ProviderInspectionFailed(str(exc)) from exc
            if not response.is_schema_valid():
                raise ProviderInspectionFailed(
                    f"provider returned schema-invalid output for {rule.detection_point_code!r}",
                    schema_error=True,
                )
            disposition = _coerce_disposition(response, content)
            results.append(_build_result(
                run, session, tenant_id, rule.detection_point_code, "visual",
                confirmed_visual_rule_id=rule.id, visual_rule_memory_id=rule.source_memory_id,
                disposition=disposition, response=response,
                image_reference=image_refs[0], capture_metadata=capture_metadata,
                provider=provider,
            ))

        # Physical measurement points never get an AI pass — measurement_required.
        for p in physical_points:
            results.append(_build_result(
                run, session, tenant_id, p.proposed_code, "physical_measurement",
                confirmed_visual_rule_id=None, visual_rule_memory_id=None,
                disposition=DISPOSITION_MEASUREMENT, response=None,
                image_reference=image_refs[0], capture_metadata=capture_metadata,
                provider=provider,
                review_conditions=["physical measurement required — not an AI-primary decision"],
            ))
    except ProviderInspectionFailed as exc:
        db.rollback()
        run = db.query(ProductionInspectionRun).filter_by(id=run.id).first()
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = _now()
        db.commit()
        db.refresh(run)
        from src.qc_model import observability
        event = (observability.EV_SCHEMA_VALIDATION_ERROR if exc.schema_error
                 else observability.EV_PROVIDER_ERROR)
        observability.record(event, tenant_id=tenant_id, run_id=run.id, provider=provider.provider_name,
                             error=type(exc.__cause__ or exc).__name__)
        observability.record(observability.EV_PRODUCTION_INSPECTION_RUN, tenant_id=tenant_id,
                             run_id=run.id, status="failed")
        return run

    for r in results:
        db.add(r)

    run.overall_disposition = _overall_disposition([r.disposition for r in results])
    run.detection_result_count = len(results)
    run.status = "completed"
    run.completed_at = _now()
    db.flush()

    # Append-only evidence packet.
    db.add(ProductionEvidencePacket(
        id=_uid(), tenant_id=tenant_id, run_id=run.id, training_pack_id=session.training_pack_id,
        packet_json=_build_packet(run, session, captures, results, provider),
    ))
    db.commit()
    db.refresh(run)
    from src.qc_model import observability
    review_n = sum(1 for r in results if r.disposition in (DISPOSITION_REVIEW, "capture_retry_required"))
    observability.record(observability.EV_PRODUCTION_INSPECTION_RUN, tenant_id=tenant_id, run_id=run.id,
                         status="completed", overall=run.overall_disposition,
                         detections=run.detection_result_count, provider=provider.provider_name)
    if review_n:
        observability.record(observability.EV_REVIEW_REQUIRED, tenant_id=tenant_id, run_id=run.id, count=review_n)
    return run


def _coerce_disposition(response, content: dict) -> str:
    disposition = response.disposition
    evidence_required = content.get("evidence_required") or []
    # A recommended pass without required evidence must not stand — review it.
    if disposition == DISPOSITION_PASS:
        if evidence_required and not response.evidence_regions:
            return DISPOSITION_REVIEW
        if response.review_required_conditions:
            return DISPOSITION_REVIEW
    return disposition


def _build_result(
    run, session, tenant_id, detection_point_code, checkpoint_category, *,
    confirmed_visual_rule_id, visual_rule_memory_id, disposition, response,
    image_reference, capture_metadata, provider, review_conditions=None,
) -> ProductionDetectionResult:
    return ProductionDetectionResult(
        id=_uid(), tenant_id=tenant_id, run_id=run.id, session_id=session.id,
        training_pack_id=session.training_pack_id,
        detection_point_code=detection_point_code,
        confirmed_visual_rule_id=confirmed_visual_rule_id,
        visual_rule_memory_id=visual_rule_memory_id,
        checkpoint_category=checkpoint_category,
        disposition=disposition,
        observed_features_json=list(response.observed_features) if response else [],
        defect_features_json=list(response.defect_features) if response else [],
        normal_features_matched_json=list(response.normal_features_matched) if response else [],
        evidence_regions_json=list(response.evidence_regions) if response else [],
        review_required_conditions_json=(
            list(response.review_required_conditions) if response else list(review_conditions or [])
        ),
        source_image_reference=image_reference,
        capture_metadata_json=capture_metadata,
        confidence=float(response.confidence) if response else 0.0,
        uncertainty=response.uncertainty if response else "",
        provider=provider.provider_name, model=provider.model_name,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        raw_provider_response_json=(dict(response.raw_response) if response and response.raw_response else None),
    )


# Recommendation / decision families for the human-override metric.
_MODEL_FAMILY = {
    DISPOSITION_PASS: "pass",
    DISPOSITION_REJECT: "reject",
    DISPOSITION_REVIEW: "review",
    DISPOSITION_CAPTURE_RETRY: "review",
    DISPOSITION_MEASUREMENT: "review",
}
_HUMAN_FAMILY = {
    "pass": "pass", "accept": "pass",
    "reject": "reject", "fail": "reject", "rework": "reject",
    "review": "review", "review_required": "review",
}


def _model_recommendation_family(recommended: str) -> str:
    return _MODEL_FAMILY.get((recommended or "").strip().lower(), "review")


def _human_decision_family(decision: str) -> str:
    return _HUMAN_FAMILY.get((decision or "").strip().lower(), "review")


def _is_human_override(recommended: str, decision: str) -> bool:
    """True when the human decision family differs from the model recommendation
    family. Matching review/review outcomes are not overrides."""
    return _model_recommendation_family(recommended) != _human_decision_family(decision)


def _overall_disposition(dispositions: list[str]) -> str:
    if not dispositions:
        return DISPOSITION_REVIEW
    if DISPOSITION_REJECT in dispositions:
        return DISPOSITION_REJECT
    # Any non-pass recommendation means the run cannot recommend a clean pass.
    if any(d != DISPOSITION_PASS for d in dispositions):
        return DISPOSITION_REVIEW
    return DISPOSITION_PASS


def _build_packet(run, session, captures, results, provider) -> dict:
    return {
        "run_id": run.id,
        "session_id": session.id,
        "training_pack_id": session.training_pack_id,
        "provider": provider.provider_name,
        "model": provider.model_name,
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "overall_disposition": run.overall_disposition,
        "captures": [{"image_reference": c.image_reference, "metadata": c.capture_metadata_json} for c in captures],
        "detection_results": [
            {
                "detection_point_code": r.detection_point_code,
                "checkpoint_category": r.checkpoint_category,
                "disposition": r.disposition,
                "confirmed_visual_rule_id": r.confirmed_visual_rule_id,
                "visual_rule_memory_id": r.visual_rule_memory_id,
                "evidence_regions": r.evidence_regions_json,
                "confidence": r.confidence,
                "uncertainty": r.uncertainty,
                "review_required_conditions": r.review_required_conditions_json,
            }
            for r in results
        ],
        "human_final_decision_required": True,
    }


def get_run(db: Session, run_id: str, tenant_id: str = "default") -> ProductionInspectionRun:
    run = db.query(ProductionInspectionRun).filter_by(id=run_id, tenant_id=tenant_id).first()
    if run is None:
        raise RunNotFound(f"Production run {run_id!r} not found")
    return run


def list_detection_results(db: Session, run_id: str, tenant_id: str = "default") -> list[ProductionDetectionResult]:
    get_run(db, run_id, tenant_id)
    return (
        db.query(ProductionDetectionResult)
        .filter_by(run_id=run_id, tenant_id=tenant_id)
        .order_by(ProductionDetectionResult.created_at.asc())
        .all()
    )


def get_evidence_packet(db: Session, run_id: str, tenant_id: str = "default") -> Optional[ProductionEvidencePacket]:
    get_run(db, run_id, tenant_id)
    return (
        db.query(ProductionEvidencePacket)
        .filter_by(run_id=run_id, tenant_id=tenant_id)
        .order_by(ProductionEvidencePacket.created_at.desc())
        .first()
    )


# ── Human final decision (the only finalization) ─────────────────────────────


def record_final_decision(
    db: Session,
    run_id: str,
    decision: str,
    decided_by: str,
    tenant_id: str = "default",
    comment: str = "",
) -> HumanFinalDecision:
    run = get_run(db, run_id, tenant_id)
    if decision not in VALID_FINAL_DECISIONS:
        raise InvalidFinalDecision(f"decision must be one of {sorted(VALID_FINAL_DECISIONS)}, got {decision!r}")
    if not decided_by or not decided_by.strip():
        raise InvalidFinalDecision("a human decision requires an operator/supervisor identity")
    record = HumanFinalDecision(
        id=_uid(), tenant_id=tenant_id, run_id=run.id, training_pack_id=run.training_pack_id,
        decision=decision, decided_by=decided_by, comment=comment,
        recommended_disposition=run.overall_disposition,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    # Human override = the human decision family differs from the model
    # recommendation family (pass / reject / review). A model review-family
    # recommendation followed by a human review decision is a match, not an
    # override; clearing a review to pass, or contradicting a pass/reject, is.
    from src.qc_model import observability
    if _is_human_override(run.overall_disposition or "", decision):
        observability.record(observability.EV_HUMAN_OVERRIDE, tenant_id=tenant_id, run_id=run.id,
                             human_decision=decision, recommended=run.overall_disposition, decided_by=decided_by)
    return record


def get_final_decisions(db: Session, run_id: str, tenant_id: str = "default") -> list[HumanFinalDecision]:
    get_run(db, run_id, tenant_id)
    return (
        db.query(HumanFinalDecision)
        .filter_by(run_id=run_id, tenant_id=tenant_id)
        .order_by(HumanFinalDecision.created_at.asc())
        .all()
    )
