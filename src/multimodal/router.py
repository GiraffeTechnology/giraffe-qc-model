"""CapabilityRouter — orchestrates capability pipeline with fail-closed policy."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.multimodal.capabilities import (
    defect_grounding,
    image_quality,
    qc_inspection,
)
from src.multimodal.config import (
    qc_cloud_can_override_local_fail,
    qc_routing_mode,
)
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import (
    DefectGroundingResult,
    ImageQualityAssessment,
    QCEvidence,
    QCInspectionResult,
    QCItemResult,
)

logger = logging.getLogger(__name__)


class RoutingContext(BaseModel):
    tenant_id: str
    sku_id: str
    standard_id: str
    inspection_id: str


class RouterResult(BaseModel):
    inspection: QCInspectionResult
    image_quality: ImageQualityAssessment | None = None
    defect_grounding: list[DefectGroundingResult] = []
    routing_mode: str
    fallback_used: bool = False
    fallback_reason: str | None = None


def _all_review_required(
    qc_points: list[dict[str, Any]],
    reason: str,
    engine: str = "multimodal_router",
    provider: str = "none",
    model_name: str = "none",
) -> QCInspectionResult:
    items = [
        QCItemResult(
            qc_point_id=p["qc_point_id"],
            qc_point_code=p.get("qc_point_code", ""),
            name=p.get("name", ""),
            result="review_required",
            confidence=0.0,
            reason=reason,
            evidence=QCEvidence(review_required_reason=reason),
        )
        for p in qc_points
    ]
    return QCInspectionResult(
        overall_result="review_required",
        engine=engine,
        provider=provider,
        model_name=model_name,
        confidence=0.0,
        items=items,
        fallback={"used": True, "reason": reason},
        summary=f"Inspection deferred: {reason}",
    )


def _image_exists(path: str) -> bool:
    return bool(path) and Path(path).exists()


class CapabilityRouter:
    """Orchestrates the QC capability pipeline.

    Flow:
    1. Validate inputs (image existence)
    2. Image quality assessment
    3. If unusable → review_required / retake
    4. Run QC inspection
    5. If fail/review_required → defect grounding
    6. Merge evidence
    7. Apply final policy (fail-closed, no silent cloud override)
    """

    def __init__(self, provider: MultimodalProvider) -> None:
        self._provider = provider

    def run(
        self,
        standard_image_paths: list[str],
        captured_image_path: str,
        qc_points: list[dict[str, Any]],
        context: RoutingContext,
        simulated_local_result: str | None = None,
    ) -> RouterResult:
        mode = qc_routing_mode()

        # 1. Validate captured image path
        if not _image_exists(captured_image_path):
            result = _all_review_required(
                qc_points,
                reason="captured_image_not_found",
                engine="multimodal_router",
            )
            return RouterResult(
                inspection=result,
                routing_mode=mode,
                fallback_used=True,
                fallback_reason="captured_image_not_found",
            )

        # 2. Image quality assessment
        iq_result: ImageQualityAssessment | None = None
        try:
            iq_result = image_quality.assess_image_quality(
                provider=self._provider,
                image_path=captured_image_path,
            )
        except Exception as exc:
            logger.warning("Image quality assessment failed: %s", exc)

        # 3. If image unusable → stop
        if iq_result is not None and not iq_result.usable:
            reason = f"image_not_usable: {iq_result.recommended_action}"
            result = _all_review_required(
                qc_points,
                reason=reason,
                engine="multimodal_router",
            )
            return RouterResult(
                inspection=result,
                image_quality=iq_result,
                routing_mode=mode,
                fallback_used=True,
                fallback_reason=reason,
            )

        # 4. Simulated local fail is final (fail-closed policy)
        if simulated_local_result == "fail" and not qc_cloud_can_override_local_fail():
            result = _all_review_required(
                qc_points,
                reason="local_fail_is_final",
                engine="multimodal_router",
            )
            return RouterResult(
                inspection=result,
                image_quality=iq_result,
                routing_mode=mode,
                fallback_used=False,
                fallback_reason="local_fail_is_final",
            )

        # 5. Run QC inspection
        ctx_dict = context.model_dump()
        inspection_result = qc_inspection.run_qc_inspection(
            provider=self._provider,
            standard_image_paths=standard_image_paths,
            captured_image_path=captured_image_path,
            qc_points=qc_points,
            context=ctx_dict,
        )

        # 6. Defect grounding for fail/review items
        grounding: list[DefectGroundingResult] = []
        failed_items = [
            {
                "qc_point_id": item.qc_point_id,
                "qc_point_code": item.qc_point_code,
                "name": item.name,
                "result": item.result,
                "reason": item.reason,
            }
            for item in inspection_result.items
            if item.result in ("fail", "review_required")
        ]

        if failed_items:
            std_path = standard_image_paths[0] if standard_image_paths else None
            try:
                grounding = defect_grounding.ground_defects(
                    provider=self._provider,
                    captured_image_path=captured_image_path,
                    standard_image_path=std_path,
                    failed_items=failed_items,
                )
            except Exception as exc:
                logger.warning("Defect grounding failed: %s", exc)

        # 7. Merge defect grounding into item evidence
        grounding_by_id = {g.qc_point_id: g for g in grounding}
        merged_items = []
        for item in inspection_result.items:
            ev = item.evidence
            if item.result in ("fail", "review_required") and item.qc_point_id in grounding_by_id:
                g = grounding_by_id[item.qc_point_id]
                ev = QCEvidence(
                    image_quality=iq_result,
                    visual_regions=g.visual_regions,
                    defect_grounding=[g],
                    standard_reference=ev.standard_reference,
                    production_observation=ev.production_observation,
                    model_reasoning_summary=ev.model_reasoning_summary,
                    review_required_reason=ev.review_required_reason,
                )
            elif iq_result is not None:
                ev = QCEvidence(
                    image_quality=iq_result,
                    visual_regions=ev.visual_regions,
                    standard_reference=ev.standard_reference,
                    production_observation=ev.production_observation,
                    model_reasoning_summary=ev.model_reasoning_summary,
                )
            merged_items.append(item.model_copy(update={"evidence": ev}))

        final_inspection = inspection_result.model_copy(update={"items": merged_items})

        return RouterResult(
            inspection=final_inspection,
            image_quality=iq_result,
            defect_grounding=grounding,
            routing_mode=mode,
            fallback_used=final_inspection.fallback.get("used", False),
            fallback_reason=final_inspection.fallback.get("reason"),
        )
