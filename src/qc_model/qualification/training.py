"""Training-judgment recording and per-decision admin review (PRD §9.5-9.8).

Each call to :func:`record_training_judgment` runs the same CV+VLM evidence
pipeline a real inspection uses (src.inspection.cv_pipeline,
src.qc_model.studio.ai_gateway) against one labeled sample and stores the
result awaiting the administrator's review. Only
:func:`submit_training_decision` -- an explicit admin action -- turns it
into a counted training sample; see
src.qc_model.qualification.training_gate for how reviewed judgments become
the rolling-window publish gate.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.db.models import _utcnow
from src.db.sku_models import QCDetectionPoint
from src.db.training_models import QCTrainingJudgment
from src.inspection.cv_pipeline import run_cv_for_points
from src.qc_model.studio import ai_gateway

_GROUND_TRUTH_LABELS = ("qualified", "unqualified")
_REQUIRED_CORRECTION_FIELDS = ("point_code", "model_error", "correct_conclusion", "correct_facts")


class TrainingError(ValueError):
    """A training-step request could not be satisfied (fail closed)."""


def _uid() -> str:
    return uuid.uuid4().hex


def record_training_judgment(
    db: Session,
    *,
    tenant_id: str,
    sku_id: str,
    standard_revision_id: str,
    image_path: Path,
    mime_type: str,
    language: str,
    ground_truth_label: str,
    evidence_root: Path,
    ground_truth_notes: Optional[str] = None,
) -> QCTrainingJudgment:
    """Run one CV+VLM training judgment against a labeled sample.

    The sample must be a real, independently captured image with a known
    ground truth -- fixture reuse, mock providers, and repeated submission
    of the same sample are a data-quality problem for the calling admin
    flow to prevent, not something this function can detect from the image
    alone (PRD §9.3: "fixture、mock、重复提交和模型复述不得计入").
    """
    if ground_truth_label not in _GROUND_TRUTH_LABELS:
        raise TrainingError(f"ground_truth_label must be one of {_GROUND_TRUTH_LABELS}")

    points = (
        db.query(QCDetectionPoint)
        .filter_by(standard_revision_id=standard_revision_id, is_active=True)
        .order_by(QCDetectionPoint.sort_order)
        .all()
    )
    if not points:
        raise TrainingError("standard revision has no active detection points to train against")

    judgment_id = _uid()
    cv_records, cv_prompt_points = run_cv_for_points(
        db, tenant_id=tenant_id, points=points, image_path=image_path,
        evidence_root=evidence_root, request_id=judgment_id,
    )
    cv_context = None
    if cv_prompt_points:
        cv_context = {
            "schema_version": "1.0", "points": cv_prompt_points,
            "verdict_effect": "informational_only",
        }
    checkpoint_contract = [
        {
            "point_code": p.point_code, "label": p.label, "description": p.description,
            "method_hint": p.method_hint, "expected_value": p.expected_value,
            "pass_criteria": p.pass_criteria,
        }
        for p in points
    ]
    result = ai_gateway.inspect_image(
        image_path=image_path, mime_type=mime_type, language=language,
        checkpoints=checkpoint_contract, cv_context=cv_context,
    )
    # A training sample must be a clean, unambiguous verdict to score
    # against ground truth: only a unanimous "pass" across every checkpoint
    # counts as the model saying "qualified" -- any fail/not_visible/
    # low_confidence checkpoint means the model did not confidently call it
    # qualified, so it scores as "fail" for training purposes (the same
    # fail-closed default used throughout this pipeline).
    overall_result = "pass" if all(
        item["result"] == "pass" for item in result["checkpoint_results"]
    ) else "fail"
    is_false_pass = ground_truth_label == "unqualified" and overall_result == "pass"

    judgment = QCTrainingJudgment(
        id=judgment_id,
        tenant_id=tenant_id,
        sku_id=sku_id,
        standard_revision_id=standard_revision_id,
        sample_image_path=str(image_path),
        ground_truth_label=ground_truth_label,
        ground_truth_notes=ground_truth_notes,
        cv_evidence_json=cv_records,
        model_provider=(result.get("assistant") or {}).get("provider"),
        model_name=(result.get("assistant") or {}).get("model"),
        model_elapsed_ms=(result.get("assistant") or {}).get("elapsed_ms"),
        model_overall_result=overall_result,
        model_checkpoint_results_json=result["checkpoint_results"],
        status="awaiting_admin_review",
        is_false_pass=is_false_pass,
        created_at=_utcnow(),
    )
    db.add(judgment)
    db.commit()
    db.refresh(judgment)
    return judgment


def list_pending_judgments(
    db: Session, *, tenant_id: str, sku_id: str, standard_revision_id: Optional[str] = None,
) -> list[QCTrainingJudgment]:
    query = db.query(QCTrainingJudgment).filter_by(
        tenant_id=tenant_id, sku_id=sku_id, status="awaiting_admin_review",
    )
    if standard_revision_id:
        query = query.filter_by(standard_revision_id=standard_revision_id)
    return query.order_by(QCTrainingJudgment.created_at.asc()).all()


def submit_training_decision(
    db: Session,
    *,
    judgment_id: str,
    tenant_id: str,
    admin_id: str,
    decision: str,
    correction: Optional[dict[str, Any]] = None,
) -> QCTrainingJudgment:
    """Record the administrator's per-decision review of one training judgment.

    Fail-closed and append-only (PRD §9.7 items 1-3): a judgment can be
    reviewed exactly once, an "incorrect" decision requires every
    correction field, and a decision on an unknown judgment or one already
    reviewed is refused rather than silently accepted or overwritten.
    """
    if decision not in ("correct", "incorrect"):
        raise TrainingError("decision must be 'correct' or 'incorrect'")
    if not admin_id or not str(admin_id).strip():
        raise TrainingError("admin_id is required to record a decision")

    judgment = db.query(QCTrainingJudgment).filter_by(id=judgment_id, tenant_id=tenant_id).first()
    if judgment is None:
        raise TrainingError("training judgment not found")
    if judgment.status == "reviewed":
        raise TrainingError(
            "training judgment already reviewed; decisions are append-only and cannot be resubmitted"
        )

    if decision == "incorrect":
        if not isinstance(correction, dict):
            raise TrainingError("correction is required when decision is 'incorrect'")
        missing = [f for f in _REQUIRED_CORRECTION_FIELDS if not str(correction.get(f) or "").strip()]
        if missing:
            raise TrainingError(f"correction missing required fields: {missing}")
        judgment.correction_json = {f: str(correction[f]).strip()[:2000] for f in _REQUIRED_CORRECTION_FIELDS}

    judgment.admin_decision = decision
    judgment.admin_id = str(admin_id).strip()
    judgment.status = "reviewed"
    judgment.reviewed_at = _utcnow()
    db.commit()
    db.refresh(judgment)
    return judgment


def judgment_view(judgment: QCTrainingJudgment) -> dict[str, Any]:
    return {
        "id": judgment.id,
        "sku_id": judgment.sku_id,
        "standard_revision_id": judgment.standard_revision_id,
        "ground_truth_label": judgment.ground_truth_label,
        "ground_truth_notes": judgment.ground_truth_notes,
        "model_provider": judgment.model_provider,
        "model_name": judgment.model_name,
        "model_elapsed_ms": judgment.model_elapsed_ms,
        "model_overall_result": judgment.model_overall_result,
        "checkpoint_results": judgment.model_checkpoint_results_json or [],
        "cv_evidence": judgment.cv_evidence_json or [],
        "status": judgment.status,
        "admin_decision": judgment.admin_decision,
        "admin_id": judgment.admin_id,
        "reviewed_at": judgment.reviewed_at.isoformat() if judgment.reviewed_at else None,
        "correction": judgment.correction_json,
        "is_false_pass": judgment.is_false_pass,
        "created_at": judgment.created_at.isoformat(),
    }


__all__ = [
    "TrainingError",
    "judgment_view",
    "list_pending_judgments",
    "record_training_judgment",
    "submit_training_decision",
]
