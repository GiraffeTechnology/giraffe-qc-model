"""Rule-authoring service (PR 22 §6, §8).

Creates a RuleAuthoringJob, runs the authoring provider over one source
fragment (or a whole extraction job's fragments), validates + guards the output,
and persists proposals into the reused PR 20 proposal table with `status =
proposed`. Fail-closed: provider failure or malformed output → job `failed`,
zero proposals persisted.

Proposals reuse PR 20's ``ProposalStatus`` and approval fields; there is NO
Training Pack write path in this module.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal
from src.db.qc_source_models import QCSourceFragment
from src.qc_model.authoring.provider import (
    AuthoringFragmentInput,
    QCRuleAuthoringProvider,
    QCRuleAuthoringRequest,
    QCRuleAuthoringResponse,
    get_authoring_provider,
)
from src.qc_model.authoring.validator import validate_response
from src.qc_model.learning.schemas import ProposalStatus


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthoringJobNotFound(ValueError):
    pass


class FragmentNotFound(ValueError):
    pass


# ── Fragment lookup (tenant-scoped, reuses PR 21 tables) ───────────────────


def _get_fragment(db: Session, fragment_id: str, tenant_id: str) -> QCSourceFragment:
    frag = (
        db.query(QCSourceFragment)
        .filter_by(id=fragment_id, tenant_id=tenant_id)
        .first()
    )
    if frag is None:
        raise FragmentNotFound(f"Source fragment {fragment_id!r} not found")
    return frag


def _fragments_for_job(db: Session, extraction_job_id: str, tenant_id: str) -> list[QCSourceFragment]:
    return (
        db.query(QCSourceFragment)
        .filter_by(extraction_job_id=extraction_job_id, tenant_id=tenant_id)
        .order_by(QCSourceFragment.created_at.asc())
        .all()
    )


# ── Run authoring ─────────────────────────────────────────────────────────


def _run(
    db: Session,
    tenant_id: str,
    training_pack_id: str,
    fragments: list[QCSourceFragment],
    *,
    source_id: Optional[str] = None,
    source_fragment_id: Optional[str] = None,
    extraction_job_id: Optional[str] = None,
    provider: Optional[QCRuleAuthoringProvider] = None,
    created_by: Optional[str] = None,
) -> RuleAuthoringJob:
    job = RuleAuthoringJob(
        id=_uid(),
        tenant_id=tenant_id,
        training_pack_id=training_pack_id,
        source_id=source_id,
        source_fragment_id=source_fragment_id,
        extraction_job_id=extraction_job_id,
        status="running",
        created_by=created_by,
    )
    db.add(job)
    db.commit()

    provider = provider or get_authoring_provider()
    job.provider = provider.provider_name
    job.model = provider.model_name
    db.commit()

    request = QCRuleAuthoringRequest(
        training_pack_id=training_pack_id,
        tenant_id=tenant_id,
        fragments=[AuthoringFragmentInput(fragment_id=f.id, text=f.text) for f in fragments],
    )

    try:
        response = provider.author_rules(request)
    except Exception as exc:  # fail closed
        response = QCRuleAuthoringResponse(
            provider=provider.provider_name,
            model=provider.model_name,
            valid=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    validation = validate_response(response)
    if not validation.valid:
        # Fail closed — persist NO proposals.
        job.status = "failed"
        job.error_message = "; ".join(validation.errors) or "invalid_authoring_output"
        job.completed_at = _now()
        db.commit()
        db.refresh(job)
        return job

    for vp in validation.proposals:
        db.add(
            QCLearnedDetectionPointProposal(
                id=_uid(),
                tenant_id=tenant_id,
                learning_job_id=None,  # authored, not from a learning job
                rule_authoring_job_id=job.id,
                source_fragment_id=vp.source_fragment_id,
                source_requirement=None,
                proposed_code=vp.proposed_code,
                proposed_name=vp.proposed_name,
                proposed_checkpoint_category=vp.checkpoint_category,
                proposed_ai_role=vp.ai_role,
                severity=vp.severity,
                normal_visual_features_json=vp.normal_visual_features,
                defect_visual_features_json=vp.defect_visual_features,
                known_pseudo_defects_json=vp.known_pseudo_defects,
                decision_rule=vp.decision_rule,
                review_required_conditions_json=vp.review_required_conditions,
                evidence_required=bool(vp.evidence_required),
                evidence_required_json=vp.evidence_required,
                confidence=vp.confidence,
                uncertainties_json=vp.questions_or_ambiguities,
                guard_override_note=vp.guard_override_note or None,
                status=ProposalStatus.PROPOSED.value,
            )
        )

    job.proposal_count = len(validation.proposals)
    job.status = "completed"
    job.completed_at = _now()
    db.commit()
    db.refresh(job)
    return job


def propose_rules_for_fragment(
    db: Session,
    fragment_id: str,
    tenant_id: str = "default",
    provider: Optional[QCRuleAuthoringProvider] = None,
    created_by: Optional[str] = None,
) -> RuleAuthoringJob:
    frag = _get_fragment(db, fragment_id, tenant_id)
    return _run(
        db, tenant_id, frag.training_pack_id, [frag],
        source_id=frag.source_id,
        source_fragment_id=frag.id,
        extraction_job_id=frag.extraction_job_id,
        provider=provider,
        created_by=created_by,
    )


def propose_rules_for_extraction_job(
    db: Session,
    extraction_job_id: str,
    tenant_id: str = "default",
    provider: Optional[QCRuleAuthoringProvider] = None,
    created_by: Optional[str] = None,
) -> RuleAuthoringJob:
    fragments = _fragments_for_job(db, extraction_job_id, tenant_id)
    training_pack_id = fragments[0].training_pack_id if fragments else ""
    source_id = fragments[0].source_id if fragments else None
    return _run(
        db, tenant_id, training_pack_id, fragments,
        source_id=source_id,
        extraction_job_id=extraction_job_id,
        provider=provider,
        created_by=created_by,
    )


# ── Read + approval (reuses PR 20 ProposalStatus) ─────────────────────────


def get_authoring_job(db: Session, job_id: str, tenant_id: str = "default") -> RuleAuthoringJob:
    job = db.query(RuleAuthoringJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        raise AuthoringJobNotFound(f"Rule authoring job {job_id!r} not found")
    return job


def list_job_proposals(
    db: Session, job_id: str, tenant_id: str = "default"
) -> list[QCLearnedDetectionPointProposal]:
    get_authoring_job(db, job_id, tenant_id)  # tenant check first
    return (
        db.query(QCLearnedDetectionPointProposal)
        .filter_by(rule_authoring_job_id=job_id, tenant_id=tenant_id)
        .order_by(QCLearnedDetectionPointProposal.created_at.asc())
        .all()
    )


def _get_proposal(db, proposal_id, tenant_id) -> QCLearnedDetectionPointProposal:
    p = (
        db.query(QCLearnedDetectionPointProposal)
        .filter_by(id=proposal_id, tenant_id=tenant_id)
        .first()
    )
    if p is None:
        raise ValueError(f"Proposal {proposal_id!r} not found")
    return p


def approve_proposal(db, proposal_id, reviewer_id, tenant_id: str = "default", edit: Optional[dict] = None):
    """Approve (optionally edit) a proposal. Reuses PR 20 ProposalStatus + fields.

    An edited checkpoint_category re-runs the physical-measurement guard so an
    edit can never leave a physical measurement AI-primary.
    """
    from src.qc_model.schemas.checkpoint import default_ai_role, is_supported_category

    p = _get_proposal(db, proposal_id, tenant_id)
    if edit:
        if "proposed_checkpoint_category" in edit:
            cat = edit["proposed_checkpoint_category"]
            if cat and not is_supported_category(cat):
                raise ValueError(f"Unsupported checkpoint category: {cat!r}")
            p.proposed_checkpoint_category = cat
            # Re-derive role from the edited category (guard survives edits).
            p.proposed_ai_role = default_ai_role(cat).value if cat else ""
        for key in ("severity", "decision_rule", "proposed_ai_role"):
            if key in edit:
                setattr(p, key, edit[key])
        # If category is physical_measurement, force record_only no matter what.
        if p.proposed_checkpoint_category == "physical_measurement":
            p.proposed_ai_role = "record_only"
    p.status = ProposalStatus.APPROVED.value
    p.approved_by = reviewer_id
    p.approved_at = _now()
    db.commit()
    db.refresh(p)
    return p


def reject_proposal(db, proposal_id, reviewer_id, tenant_id: str = "default"):
    p = _get_proposal(db, proposal_id, tenant_id)
    p.status = ProposalStatus.REJECTED.value
    p.approved_by = reviewer_id
    p.approved_at = _now()
    db.commit()
    db.refresh(p)
    return p
