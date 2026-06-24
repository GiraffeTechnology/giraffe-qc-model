"""Human review and override service."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from src.db.qc_checkpoint_models import (
    QCHumanReview, QCInspectionJob, QCCheckpointResult,
    QCTrainingSample, QCAuditEvent
)


def create_human_review(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    reviewer_id: Optional[str] = None,
    review_status: str,
    final_result: str,
    review_comment: Optional[str] = None,
) -> QCHumanReview:
    review = QCHumanReview(
        inspection_job_id=inspection_job.id,
        reviewer_id=reviewer_id,
        review_status=review_status,
        original_result=inspection_job.inspection_status,
        final_result=final_result,
        review_comment=review_comment,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(review)
    inspection_job.inspection_status = "human_reviewed"
    _audit(
        db,
        entity_type="qc_inspection_job",
        entity_id=inspection_job.id,
        event_type="human_reviewed",
        actor_id=reviewer_id,
        event_json={"review_status": review_status, "final_result": final_result},
    )
    db.commit()
    return review


def override_result(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    reviewer_id: Optional[str] = None,
    final_result: str,
    review_comment: Optional[str] = None,
) -> QCHumanReview:
    return create_human_review(
        db,
        inspection_job=inspection_job,
        reviewer_id=reviewer_id,
        review_status="overridden",
        final_result=final_result,
        review_comment=review_comment,
    )


def confirm_result(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    reviewer_id: Optional[str] = None,
    review_comment: Optional[str] = None,
) -> QCHumanReview:
    current = inspection_job.inspection_status
    return create_human_review(
        db,
        inspection_job=inspection_job,
        reviewer_id=reviewer_id,
        review_status="confirmed",
        final_result=current,
        review_comment=review_comment,
    )


def send_to_reinspection(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    reviewer_id: Optional[str] = None,
    review_comment: Optional[str] = None,
) -> QCHumanReview:
    return create_human_review(
        db,
        inspection_job=inspection_job,
        reviewer_id=reviewer_id,
        review_status="needs_reinspection",
        final_result="review_required",
        review_comment=review_comment,
    )


def create_training_samples_from_review(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    review: QCHumanReview,
) -> list[QCTrainingSample]:
    cp_results = (
        db.query(QCCheckpointResult)
        .filter_by(inspection_job_id=inspection_job.id)
        .all()
    )
    samples: list[QCTrainingSample] = []
    for cp_result in cp_results:
        if review.review_status == "overridden":
            sample_type = "correction"
        elif cp_result.result == "pass":
            sample_type = "pass_case"
        elif cp_result.result == "fail":
            sample_type = "fail_case"
        else:
            sample_type = "review_case"

        sample = QCTrainingSample(
            inspection_job_id=inspection_job.id,
            checkpoint_id=cp_result.checkpoint_id,
            sample_type=sample_type,
            label_json={
                "checkpoint_code": cp_result.checkpoint_code,
                "ai_result": cp_result.result,
                "human_result": review.final_result,
                "observed": cp_result.observed_json,
            },
            source="human_review",
        )
        db.add(sample)
        samples.append(sample)
    db.commit()
    return samples


def _audit(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    event_type: str,
    actor_id: Optional[str] = None,
    event_json: Optional[dict] = None,
) -> None:
    db.add(QCAuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor_id=actor_id,
        event_json=event_json or {},
    ))
