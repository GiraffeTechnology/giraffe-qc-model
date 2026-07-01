"""QC rule-learning service layer (PRD §10, §11).

Orchestrates the learning workflow: create job -> add inputs -> run learning
(runtime policy + provider + validation + persistence + report) -> supervisor
review. Depends only on the provider *abstraction* and registry — never a
vendor class.

Fail-closed everywhere: forbidden/tablet runtime, provider failure, or invalid
output all drive the job to ``failed`` and require supervisor review. They
never create active or applied rules.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.qc_learning_models import (
    QCLearnedDetectionPointProposal,
    QCLearnedVisualRuleProposal,
    QCLearningApproval,
    QCLearningInput,
    QCLearningJob,
    QCLearningReport,
)
from src.db.sku_models import QCDetectionPoint
from src.qc_model.learning.providers.base import QCRuleLearningProvider
from src.qc_model.learning.providers.registry import get_learning_provider_for_profile
from src.qc_model.learning.report import build_report
from src.qc_model.learning.runtime_policy import evaluate_learning_runtime
from src.qc_model.learning.schemas import (
    LearningJobStatus,
    LearningSampleRefs,
    ProposalStatus,
    QCRuleLearningRequest,
    QCRuleLearningResponse,
)
from src.qc_model.learning.validator import validate_response
from src.qc_model.schemas.checkpoint import default_ai_role, is_supported_category


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LearningJobNotFound(ValueError):
    pass


def _default_provider(profile) -> QCRuleLearningProvider:
    """Resolve the default learning provider for a profile.

    Uses the deterministic mock only when explicitly allowed (dev/test);
    otherwise resolves through the registry, which fails closed in Phase 2A
    when no real backend is configured. Product logic still depends only on the
    provider abstraction — the mock is not a vendor class.
    """
    from src.qc_model.learning.config import learning_mock_allowed

    if learning_mock_allowed():
        from src.qc_model.learning.providers.mock_provider import (
            MockRuleLearningProvider,
        )

        return MockRuleLearningProvider()
    return get_learning_provider_for_profile(profile)


# ── Job + input creation ──────────────────────────────────────────────────


def create_learning_job(
    db: Session,
    training_pack_id: str,
    sku_id: str,
    station_id: str,
    tenant_id: str = "default",
    created_by: Optional[str] = None,
    runtime_profile: str = "server",
) -> QCLearningJob:
    job = QCLearningJob(
        id=_uid(),
        tenant_id=tenant_id,
        training_pack_id=training_pack_id,
        sku_id=sku_id,
        station_id=station_id,
        status=LearningJobStatus.DRAFT.value,
        runtime_profile=runtime_profile,
        created_by=created_by,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, learning_job_id: str, tenant_id: str = "default") -> QCLearningJob:
    job = (
        db.query(QCLearningJob)
        .filter_by(id=learning_job_id, tenant_id=tenant_id)
        .first()
    )
    if job is None:
        raise LearningJobNotFound(f"Learning job {learning_job_id!r} not found")
    return job


def add_operator_requirement(
    db: Session,
    learning_job_id: str,
    requirement_text: str,
    source: str = "operator_text",
    operator_id: Optional[str] = None,
    tenant_id: str = "default",
) -> QCLearningInput:
    job = get_job(db, learning_job_id, tenant_id)
    inp = QCLearningInput(
        id=_uid(),
        tenant_id=tenant_id,
        learning_job_id=job.id,
        input_type="operator_requirement",
        source=source,
        text_content=requirement_text,
        created_by=operator_id,
    )
    db.add(inp)
    if job.status == LearningJobStatus.DRAFT.value:
        job.status = LearningJobStatus.INPUT_READY.value
    db.commit()
    db.refresh(inp)
    return inp


def add_sample_refs(
    db: Session,
    learning_job_id: str,
    sample_refs: dict,
    tenant_id: str = "default",
    created_by: Optional[str] = None,
) -> QCLearningInput:
    job = get_job(db, learning_job_id, tenant_id)
    inp = QCLearningInput(
        id=_uid(),
        tenant_id=tenant_id,
        learning_job_id=job.id,
        input_type="sample_refs",
        source="uploaded_standard",
        sample_refs_json=sample_refs,
        created_by=created_by,
    )
    db.add(inp)
    if job.status == LearningJobStatus.DRAFT.value:
        job.status = LearningJobStatus.INPUT_READY.value
    db.commit()
    db.refresh(inp)
    return inp


# ── Run learning ──────────────────────────────────────────────────────────


def _gather_request(db: Session, job: QCLearningJob, runtime_profile: str) -> QCRuleLearningRequest:
    inputs = db.query(QCLearningInput).filter_by(learning_job_id=job.id).all()
    requirements = [i.text_content for i in inputs if i.input_type == "operator_requirement" and i.text_content]

    refs = LearningSampleRefs()
    for i in inputs:
        if i.input_type == "sample_refs" and i.sample_refs_json:
            data = i.sample_refs_json
            for field_name in LearningSampleRefs.model_fields:
                if field_name in data and isinstance(data[field_name], list):
                    getattr(refs, field_name).extend(data[field_name])

    existing = (
        db.query(QCDetectionPoint)
        .filter_by(sku_id=job.sku_id, tenant_id=job.tenant_id)
        .all()
    )
    return QCRuleLearningRequest(
        learning_job_id=job.id,
        training_pack_id=job.training_pack_id,
        sku_id=job.sku_id,
        station_id=job.station_id,
        runtime_profile=runtime_profile,
        operator_requirements=requirements,
        sample_refs=refs,
        existing_detection_point_codes=[dp.point_code for dp in existing],
    )


def _fail_job(db: Session, job: QCLearningJob, reason: str) -> QCLearningJob:
    """Fail a job closed and persist a supervisor-review-required report."""
    job.status = LearningJobStatus.FAILED.value
    job.error_message = reason
    report = QCLearningReport(
        id=_uid(),
        tenant_id=job.tenant_id,
        learning_job_id=job.id,
        report_json={
            "learning_job_id": job.id,
            "training_pack_id": job.training_pack_id,
            "sku_id": job.sku_id,
            "station_id": job.station_id,
            "error": reason,
            "requires_supervisor_review": True,
            "can_apply_to_training_pack": False,
        },
        requires_supervisor_review=True,
        can_apply_to_training_pack=False,
    )
    db.add(report)
    db.commit()
    db.refresh(job)
    return job


def run_learning(
    db: Session,
    learning_job_id: str,
    tenant_id: str = "default",
    requested_runtime: Optional[str] = None,
    provider: Optional[QCRuleLearningProvider] = None,
) -> QCLearningJob:
    """Run rule learning for a job. Fail-closed on every unsafe path."""
    job = get_job(db, learning_job_id, tenant_id)

    # Runtime policy (PRD §4): learning defaults to server; tablet_mnn is not
    # allowed and any unknown/deprecated runtime is forbidden. Either path fails
    # closed to a supervisor-review-required state — never silent tablet learning.
    decision = evaluate_learning_runtime(requested_runtime or job.runtime_profile)
    if not decision.allowed:
        return _fail_job(db, job, f"learning_runtime_rejected:{decision.reason}")

    profile = decision.profile
    job.runtime_profile = profile.environment.value
    job.status = LearningJobStatus.RUNNING.value
    db.commit()

    request = _gather_request(db, job, profile.environment.value)

    if provider is None:
        provider = _default_provider(profile)

    job.provider = provider.provider_name
    job.model = provider.model_name
    db.commit()

    try:
        response = provider.learn_rules(request)
    except Exception as exc:  # fail closed
        response = QCRuleLearningResponse(
            provider=provider.provider_name,
            model=provider.model_name,
            runtime_profile=profile.environment.value,
            valid=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    validation = validate_response(response)
    if not validation.valid:
        return _fail_job(db, job, f"invalid_learning_output:{';'.join(validation.errors)}")

    normalized = validation.normalized
    _persist_proposals(db, job, normalized)

    report = build_report(request, normalized)
    db.add(
        QCLearningReport(
            id=_uid(),
            tenant_id=job.tenant_id,
            learning_job_id=job.id,
            report_json=report.model_dump(mode="json"),
            requires_supervisor_review=True,
            can_apply_to_training_pack=False,
        )
    )

    job.status = LearningJobStatus.PROPOSED.value
    db.commit()
    db.refresh(job)
    return job


def _persist_proposals(db: Session, job: QCLearningJob, response: QCRuleLearningResponse) -> None:
    id_map: dict[str, str] = {}  # provider proposal_id -> db id
    for p in response.detection_point_proposals:
        db_id = _uid()
        id_map[p.proposal_id] = db_id
        db.add(
            QCLearnedDetectionPointProposal(
                id=db_id,
                tenant_id=job.tenant_id,
                learning_job_id=job.id,
                source_requirement=p.source_requirement,
                proposed_code=p.proposed_code,
                proposed_name=p.proposed_name,
                proposed_checkpoint_category=p.proposed_checkpoint_category,
                proposed_ai_role=p.proposed_ai_role,
                target_region=p.target_region,
                severity=p.severity,
                normal_visual_features_json=list(p.normal_visual_features),
                defect_visual_features_json=list(p.defect_visual_features),
                known_pseudo_defects_json=list(p.known_pseudo_defects),
                decision_rule=p.decision_rule,
                review_required_conditions_json=list(p.review_required_conditions),
                evidence_required=p.evidence_required,
                confidence=p.confidence,
                uncertainties_json=list(p.uncertainties),
                status=ProposalStatus.PROPOSED.value,
            )
        )
    for r in response.visual_rule_proposals:
        db.add(
            QCLearnedVisualRuleProposal(
                id=_uid(),
                tenant_id=job.tenant_id,
                learning_job_id=job.id,
                detection_point_proposal_id=id_map.get(r.detection_point_proposal_id),
                rule_type=r.rule_type.value if hasattr(r.rule_type, "value") else r.rule_type,
                rule_text=r.rule_text,
                source_samples_json=list(r.source_samples),
                source_requirement=r.source_requirement,
                provider=r.provider,
                model=r.model,
                runtime_profile=r.runtime_profile,
                confidence=r.confidence,
                status=ProposalStatus.PROPOSED.value,
            )
        )
    db.flush()


# ── Supervisor review ─────────────────────────────────────────────────────


def list_detection_point_proposals(
    db: Session, learning_job_id: str, tenant_id: str = "default"
) -> list[QCLearnedDetectionPointProposal]:
    return (
        db.query(QCLearnedDetectionPointProposal)
        .filter_by(learning_job_id=learning_job_id, tenant_id=tenant_id)
        .all()
    )


def _record_approval(db, job, proposal_id, action, reviewer_id, edited=None, comment=""):
    db.add(
        QCLearningApproval(
            id=_uid(),
            tenant_id=job.tenant_id,
            learning_job_id=job.id,
            proposal_type="detection_point",
            proposal_id=proposal_id,
            action=action,
            edited_payload_json=edited,
            reviewer_id=reviewer_id,
            review_comment=comment,
        )
    )


def _refresh_job_status(db: Session, job: QCLearningJob) -> None:
    proposals = list_detection_point_proposals(db, job.id, job.tenant_id)
    if not proposals:
        return
    statuses = {p.status for p in proposals}
    approved = [p for p in proposals if p.status in (ProposalStatus.APPROVED.value, ProposalStatus.APPLIED.value)]
    rejected = [p for p in proposals if p.status == ProposalStatus.REJECTED.value]

    if all(p.status == ProposalStatus.APPLIED.value for p in proposals):
        job.status = LearningJobStatus.APPLIED.value
    elif rejected and not approved:
        job.status = LearningJobStatus.REJECTED.value
    elif approved and (rejected or ProposalStatus.PROPOSED.value in statuses):
        job.status = LearningJobStatus.PARTIALLY_APPROVED.value
    elif approved and len(approved) == len(proposals):
        job.status = LearningJobStatus.APPROVED.value
    else:
        job.status = LearningJobStatus.REVIEWING.value


def approve_proposals(
    db: Session,
    learning_job_id: str,
    proposal_ids: list[str],
    reviewer_id: str,
    edits: Optional[dict[str, dict]] = None,
    tenant_id: str = "default",
) -> QCLearningJob:
    job = get_job(db, learning_job_id, tenant_id)
    edits = edits or {}
    for p in list_detection_point_proposals(db, job.id, tenant_id):
        if p.id not in proposal_ids:
            continue
        edit = edits.get(p.id)
        if edit:
            # A category edit must re-derive the AI role, otherwise a
            # supervisor correcting (e.g.) a visual proposal to
            # physical_measurement would leave a stale primary_visual_judge
            # role that apply() would write into the detection point, bypassing
            # the physical-measurement boundary. Reject unsupported categories.
            if "proposed_checkpoint_category" in edit:
                new_category = edit["proposed_checkpoint_category"]
                if not is_supported_category(new_category):
                    raise ValueError(
                        f"Unsupported checkpoint category in edit: {new_category!r}"
                    )
                p.proposed_checkpoint_category = new_category
                p.proposed_ai_role = default_ai_role(new_category).value
            for key in ("severity", "decision_rule"):
                if key in edit:
                    setattr(p, key, edit[key])
            if "review_required_conditions" in edit:
                p.review_required_conditions_json = edit["review_required_conditions"]
            if "normal_visual_features" in edit:
                p.normal_visual_features_json = edit["normal_visual_features"]
            if "defect_visual_features" in edit:
                p.defect_visual_features_json = edit["defect_visual_features"]
            if "known_pseudo_defects" in edit:
                p.known_pseudo_defects_json = edit["known_pseudo_defects"]
        p.status = ProposalStatus.APPROVED.value
        p.approved_by = reviewer_id
        p.approved_at = _now()
        _record_approval(db, job, p.id, "approve", reviewer_id, edited=edit)
    _refresh_job_status(db, job)
    db.commit()
    db.refresh(job)
    return job


def reject_proposals(
    db: Session,
    learning_job_id: str,
    proposal_ids: list[str],
    reviewer_id: str,
    comment: str = "",
    tenant_id: str = "default",
) -> QCLearningJob:
    job = get_job(db, learning_job_id, tenant_id)
    for p in list_detection_point_proposals(db, job.id, tenant_id):
        if p.id not in proposal_ids:
            continue
        p.status = ProposalStatus.REJECTED.value
        _record_approval(db, job, p.id, "reject", reviewer_id, comment=comment)
    _refresh_job_status(db, job)
    db.commit()
    db.refresh(job)
    return job


def get_report(db: Session, learning_job_id: str, tenant_id: str = "default") -> Optional[dict]:
    report = (
        db.query(QCLearningReport)
        .filter_by(learning_job_id=learning_job_id, tenant_id=tenant_id)
        .order_by(QCLearningReport.created_at.desc())
        .first()
    )
    return report.report_json if report else None
