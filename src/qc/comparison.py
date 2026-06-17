"""
Core Capability A — image comparison pipeline.

Flow: production_image → lookup sample → call LLM → write QCTask + QCResult to DB
"""
from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.db.models import QCTask, QCResult, SampleItem
from src.llm.base import LLMProvider, ImageCompareResult
from src.llm.registry import get_provider


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_comparison(
    db: Session,
    production_image: str,
    sample: SampleItem,
    requirements: str = "",
    notes: str = "",
    provider: LLMProvider | None = None,
    source_type: str = "manual",
) -> tuple[QCTask, QCResult]:
    """
    Run a single QC comparison and persist results.

    Returns (QCTask, QCResult) — both committed to DB.
    """
    llm = provider or get_provider()

    # Create task record
    task = QCTask(
        sample_id=sample.id,
        source_image_path=production_image,
        source_type=source_type,
        status="running",
        created_at=_utcnow(),
    )
    db.add(task)
    db.flush()  # get task.id before calling LLM

    try:
        result: ImageCompareResult = llm.compare_images(
            standard_paths=[sample.image_path],
            production_paths=[production_image],
            requirements=requirements,
            notes=notes,
        )
        task.status = "done"
    except Exception as exc:
        task.status = "failed"
        task.completed_at = _utcnow()
        db.commit()
        raise RuntimeError(f"LLM comparison failed for task {task.id}: {exc}") from exc

    task.completed_at = _utcnow()

    qc_result = QCResult(
        task_id=task.id,
        llm_provider=result.provider,
        model_name=result.model,
        http_status=result.http_status,
        elapsed_ms=result.elapsed_ms,
        overall_result=result.overall_result,
        similarity_score=result.similarity_score,
        severity=result.severity,
        feedback_zh=result.feedback_zh,
        feedback_en=result.feedback_en,
        deviations=result.deviations,
        llm_raw_summary=result.raw_summary,
        created_at=_utcnow(),
    )
    db.add(qc_result)
    db.commit()
    db.refresh(task)
    db.refresh(qc_result)
    return task, qc_result
