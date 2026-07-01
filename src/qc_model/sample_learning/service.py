"""VLM sample-learning service (PR 23 §4, §6).

Create sample groups, run a learning job (provider + validate + persist
observations/anchors/memory), supervisor approval, and the single
apply-to-Training-Pack path with a no-silent-overwrite guard.

Fail-closed: provider failure or malformed output → job ``failed``, no
observations / memory persisted as approvable. Apply is server-side gated on
``approved`` status and conflict detection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.qc_sample_learning_models import (
    CaptureArtifactRule,
    PseudoDefectRule,
    QCConfirmedVisualRule,
    SampleEvidenceAnchor,
    SampleGroup,
    SampleLearningJob,
    VisualFeatureObservation,
    VisualRuleMemory,
)
from src.db.sku_models import QCDetectionPoint
from src.qc_model.sample_learning.provider import (
    SampleInput,
    SampleLearningProvider,
    SampleLearningRequest,
    SampleLearningResponse,
    get_sample_learning_provider,
)
from src.qc_model.sample_learning.types import (
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    is_valid_sample_type,
)

_LIST_FIELDS = [
    "normal_visual_features",
    "acceptable_variations",
    "defect_visual_features",
    "known_pseudo_defects",
    "capture_artifact_risks",
    "evidence_required",
    "review_required_conditions",
]


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SampleGroupNotFound(ValueError):
    pass


class SampleLearningJobNotFound(ValueError):
    pass


class DetectionPointNotFound(ValueError):
    pass


class InvalidSampleType(ValueError):
    pass


class MemoryNotFound(ValueError):
    pass


class MemoryNotApproved(ValueError):
    pass


class ConfirmedRuleConflict(ValueError):
    pass


# ── Sample groups ─────────────────────────────────────────────────────────


def create_sample_group(
    db: Session,
    training_pack_id: str,
    detection_point_id: str,
    sample_type: str,
    image_references: list[str],
    tenant_id: str = "default",
    created_by: Optional[str] = None,
) -> SampleGroup:
    if not is_valid_sample_type(sample_type):
        raise InvalidSampleType(f"Invalid sample_type: {sample_type!r}")

    dp = (
        db.query(QCDetectionPoint)
        .filter_by(id=detection_point_id, tenant_id=tenant_id)
        .first()
    )
    if dp is None:
        raise DetectionPointNotFound(
            f"Detection point {detection_point_id!r} not found for tenant {tenant_id!r}"
        )

    samples = [{"sample_id": _uid(), "image_reference": ref} for ref in (image_references or [])]
    group = SampleGroup(
        id=_uid(),
        tenant_id=tenant_id,
        training_pack_id=training_pack_id,
        detection_point_id=detection_point_id,
        detection_point_code=dp.point_code,
        sample_type=sample_type,
        samples_json=samples,
        status="draft",
        created_by=created_by,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def get_sample_group(db: Session, group_id: str, tenant_id: str = "default") -> SampleGroup:
    group = db.query(SampleGroup).filter_by(id=group_id, tenant_id=tenant_id).first()
    if group is None:
        raise SampleGroupNotFound(f"Sample group {group_id!r} not found")
    return group


# ── Run learning ──────────────────────────────────────────────────────────


def _validate_observations(response: SampleLearningResponse) -> tuple[bool, list[str]]:
    if not response.valid:
        return False, [response.error or "provider_invalid"]
    for obs in response.observations:
        if not isinstance(obs, dict):
            return False, ["observation_is_not_an_object"]
        if not obs.get("source_sample_id") or not obs.get("feature_type"):
            return False, ["observation_missing_required_provenance"]
    return True, []


def run_sample_learning_job(
    db: Session,
    sample_group_id: str,
    tenant_id: str = "default",
    provider: Optional[SampleLearningProvider] = None,
    created_by: Optional[str] = None,
) -> SampleLearningJob:
    group = get_sample_group(db, sample_group_id, tenant_id)

    job = SampleLearningJob(
        id=_uid(),
        tenant_id=tenant_id,
        training_pack_id=group.training_pack_id,
        sample_group_id=group.id,
        status="running",
        created_by=created_by,
    )
    db.add(job)
    db.commit()

    provider = provider or get_sample_learning_provider()
    job.provider = provider.provider_name
    job.model = provider.model_name
    db.commit()

    request = SampleLearningRequest(
        training_pack_id=group.training_pack_id,
        tenant_id=tenant_id,
        detection_point_code=group.detection_point_code or "",
        sample_type=group.sample_type,
        samples=[
            SampleInput(sample_id=s["sample_id"], image_reference=s.get("image_reference", ""))
            for s in (group.samples_json or [])
        ],
    )

    try:
        response = provider.learn_samples(request)
    except Exception as exc:  # fail closed
        response = SampleLearningResponse(
            provider=provider.provider_name, model=provider.model_name,
            valid=False, error=f"{type(exc).__name__}: {exc}",
        )

    ok, errors = _validate_observations(response)
    if not ok:
        job.status = "failed"
        job.error_message = "; ".join(errors)
        job.completed_at = _now()
        db.commit()
        db.refresh(job)
        return job

    observation_ids: list[str] = []
    aggregate = {f: [] for f in _LIST_FIELDS}
    for obs in response.observations:
        obs_id = _uid()
        observation_ids.append(obs_id)
        db.add(
            VisualFeatureObservation(
                id=obs_id,
                tenant_id=tenant_id,
                sample_learning_job_id=job.id,
                sample_group_id=group.id,
                training_pack_id=group.training_pack_id,
                detection_point_code=obs.get("detection_point_code") or group.detection_point_code,
                source_sample_id=str(obs["source_sample_id"]),
                image_reference=obs.get("image_reference"),
                feature_type=str(obs["feature_type"]),
                evidence_region_json=obs.get("evidence_region"),
                confidence=float(obs.get("confidence") or 0.0),
                uncertainty=obs.get("uncertainty"),
                rule_implication=obs.get("rule_implication"),
                requires_human_review=bool(obs.get("requires_human_review", True)),
                normal_visual_features_json=list(obs.get("normal_visual_features") or []),
                acceptable_variations_json=list(obs.get("acceptable_variations") or []),
                defect_visual_features_json=list(obs.get("defect_visual_features") or []),
                known_pseudo_defects_json=list(obs.get("known_pseudo_defects") or []),
                capture_artifact_risks_json=list(obs.get("capture_artifact_risks") or []),
                evidence_required_json=list(obs.get("evidence_required") or []),
                review_required_conditions_json=list(obs.get("review_required_conditions") or []),
            )
        )
        # Append-only per-sample evidence anchor (provenance).
        db.add(
            SampleEvidenceAnchor(
                id=_uid(),
                tenant_id=tenant_id,
                observation_id=obs_id,
                source_sample_id=str(obs["source_sample_id"]),
                image_reference=obs.get("image_reference"),
                evidence_region_json=obs.get("evidence_region"),
            )
        )
        for f in _LIST_FIELDS:
            for item in obs.get(f) or []:
                if item not in aggregate[f]:
                    aggregate[f].append(item)

    # Aggregate one VisualRuleMemory for the group's feature type.
    feature_type = response.observations[0]["feature_type"] if response.observations else "normal_feature"
    memory = VisualRuleMemory(
        id=_uid(),
        tenant_id=tenant_id,
        sample_learning_job_id=job.id,
        training_pack_id=group.training_pack_id,
        detection_point_code=group.detection_point_code,
        feature_type=str(feature_type),
        normal_visual_features_json=aggregate["normal_visual_features"],
        acceptable_variations_json=aggregate["acceptable_variations"],
        defect_visual_features_json=aggregate["defect_visual_features"],
        known_pseudo_defects_json=aggregate["known_pseudo_defects"],
        capture_artifact_risks_json=aggregate["capture_artifact_risks"],
        evidence_required_json=aggregate["evidence_required"],
        review_required_conditions_json=aggregate["review_required_conditions"],
        observation_ids_json=observation_ids,
        status=STATUS_PROPOSED,
    )
    db.add(memory)
    db.flush()

    for pattern in aggregate["known_pseudo_defects"]:
        db.add(
            PseudoDefectRule(
                id=_uid(), tenant_id=tenant_id, training_pack_id=group.training_pack_id,
                visual_rule_memory_id=memory.id, detection_point_code=group.detection_point_code,
                pattern_text=pattern, risk_level="normal", status=STATUS_PROPOSED,
            )
        )
    for pattern in aggregate["capture_artifact_risks"]:
        db.add(
            CaptureArtifactRule(
                id=_uid(), tenant_id=tenant_id, training_pack_id=group.training_pack_id,
                visual_rule_memory_id=memory.id, detection_point_code=group.detection_point_code,
                pattern_text=pattern, status=STATUS_PROPOSED,
            )
        )

    job.observation_count = len(observation_ids)
    job.status = "completed"
    job.completed_at = _now()
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str, tenant_id: str = "default") -> SampleLearningJob:
    job = db.query(SampleLearningJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        raise SampleLearningJobNotFound(f"Sample learning job {job_id!r} not found")
    return job


def list_observations(db: Session, job_id: str, tenant_id: str = "default") -> list[VisualFeatureObservation]:
    get_job(db, job_id, tenant_id)
    return (
        db.query(VisualFeatureObservation)
        .filter_by(sample_learning_job_id=job_id, tenant_id=tenant_id)
        .order_by(VisualFeatureObservation.created_at.asc())
        .all()
    )


def list_visual_rule_memory(db: Session, job_id: str, tenant_id: str = "default") -> list[VisualRuleMemory]:
    get_job(db, job_id, tenant_id)
    return (
        db.query(VisualRuleMemory)
        .filter_by(sample_learning_job_id=job_id, tenant_id=tenant_id)
        .all()
    )


# ── Approval + apply ──────────────────────────────────────────────────────


def get_memory(db: Session, memory_id: str, tenant_id: str = "default") -> VisualRuleMemory:
    m = db.query(VisualRuleMemory).filter_by(id=memory_id, tenant_id=tenant_id).first()
    if m is None:
        raise MemoryNotFound(f"Visual rule memory {memory_id!r} not found")
    return m


def review_memory(
    db: Session,
    memory_id: str,
    action: str,
    reviewer_id: str,
    tenant_id: str = "default",
    edit: Optional[dict] = None,
    comment: str = "",
) -> VisualRuleMemory:
    """Reuse PR 20's approve/edit/reject shape for visual rule memory."""
    m = get_memory(db, memory_id, tenant_id)
    if action == "approve":
        if edit:
            for f in _LIST_FIELDS:
                if f in edit:
                    setattr(m, f"{f}_json", list(edit[f]))
        m.status = STATUS_APPROVED
    elif action == "reject":
        m.status = STATUS_REJECTED
    elif action == "edit":
        if edit:
            for f in _LIST_FIELDS:
                if f in edit:
                    setattr(m, f"{f}_json", list(edit[f]))
        # edit keeps it in proposed unless combined with approve
    else:
        raise ValueError(f"Unknown review action: {action!r}")
    m.approved_by = reviewer_id
    m.approved_at = _now()
    m.review_comment = comment or m.review_comment
    db.commit()
    db.refresh(m)
    return m


def _memory_content(m: VisualRuleMemory) -> dict:
    return {f: getattr(m, f"{f}_json") or [] for f in _LIST_FIELDS}


def apply_approved_memory(
    db: Session,
    training_pack_id: str,
    memory_id: str,
    applied_by: str,
    tenant_id: str = "default",
) -> QCConfirmedVisualRule:
    """The ONLY Training-Pack write path. Server-side gated + no silent overwrite."""
    m = get_memory(db, memory_id, tenant_id)
    if m.status != STATUS_APPROVED:
        raise MemoryNotApproved(
            f"Visual rule memory {memory_id!r} is not approved (status={m.status})"
        )

    content = _memory_content(m)
    existing = (
        db.query(QCConfirmedVisualRule)
        .filter_by(
            tenant_id=tenant_id,
            training_pack_id=training_pack_id,
            detection_point_code=m.detection_point_code,
            feature_type=m.feature_type,
        )
        .first()
    )
    if existing is not None:
        if existing.source_memory_id == m.id or existing.content_json == content:
            # Idempotent / identical — do not error, do not duplicate.
            return existing
        raise ConfirmedRuleConflict(
            "A different confirmed visual rule already exists for this detection "
            "point + feature type; supervisor must resolve the conflict explicitly."
        )

    confirmed = QCConfirmedVisualRule(
        id=_uid(),
        tenant_id=tenant_id,
        training_pack_id=training_pack_id,
        detection_point_code=m.detection_point_code,
        feature_type=m.feature_type,
        content_json=content,
        source_memory_id=m.id,
        confirmed_by=applied_by,
    )
    db.add(confirmed)
    m.status = STATUS_APPLIED
    m.applied_at = _now()
    db.commit()
    db.refresh(confirmed)
    return confirmed
