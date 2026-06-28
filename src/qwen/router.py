"""QWEN QC Router — backend mirror of the on-device Phase 5 router.

Primary inspection path is on-device Android. This router is used for:
- backend_proxy mode (server-side inspection)
- re-verification of on-device results

When cloud is disabled and no cloud_provider given, returns review_required.
"""
from __future__ import annotations

import os
from typing import List, Optional

from src.qwen.base import QwenQCProvider
from src.qwen.schema import (
    CapturePhotoInput,
    FallbackInfo,
    InspectionContext,
    InspectionItemResult,
    QcPointInput,
    QwenInspectionOutput,
    StandardPhotoInput,
)


_FINAL_RESULTS = ("pass", "fail", "review_required")


def _cloud_enabled() -> bool:
    return os.getenv("QWEN_CLOUD_ENABLED", "false").lower() == "true"


def _make_review_required(
    qc_points: List[QcPointInput],
    reason: str,
    engine: str = "router",
) -> QwenInspectionOutput:
    """Return a review_required result with all items as review_required."""
    items = [
        InspectionItemResult(
            qc_point_id=p.qc_point_id,
            qc_point_code=p.qc_point_code,
            name=p.name,
            result="review_required",
            confidence=0.0,
            reason=reason,
            evidence={},
        )
        for p in qc_points
    ]
    return QwenInspectionOutput(
        overall_result="review_required",
        engine=engine,
        model_name="none",
        confidence=0.0,
        items=items,
        fallback=FallbackInfo(used=True, reason=reason),
        summary=f"Inspection deferred: {reason}",
    )


def _make_fail(
    qc_points: List[QcPointInput],
    reason: str,
    engine: str = "router",
) -> QwenInspectionOutput:
    """Return a fail result (used when on-device result was fail and is final)."""
    items = [
        InspectionItemResult(
            qc_point_id=p.qc_point_id,
            qc_point_code=p.qc_point_code,
            name=p.name,
            result="fail",
            confidence=0.0,
            reason=reason,
            evidence={},
        )
        for p in qc_points
    ]
    return QwenInspectionOutput(
        overall_result="fail",
        engine=engine,
        model_name="none",
        confidence=0.0,
        items=items,
        fallback=FallbackInfo(used=False, reason=reason),
        summary=f"On-device inspection result: {reason}",
    )


def _normalize_provider_output(
    result: QwenInspectionOutput,
    qc_points: List[QcPointInput],
) -> QwenInspectionOutput:
    expected_ids = [p.qc_point_id for p in qc_points]
    expected_id_set = set(expected_ids)
    by_id: dict[str, InspectionItemResult] = {}

    for item in result.items:
        if item.qc_point_id not in expected_id_set:
            continue
        item_result = item.result if item.result in _FINAL_RESULTS else "review_required"
        by_id[item.qc_point_id] = item.model_copy(update={"result": item_result})

    missing_ids = []
    for point in qc_points:
        if point.qc_point_id not in by_id:
            missing_ids.append(point.qc_point_id)
            by_id[point.qc_point_id] = InspectionItemResult(
                qc_point_id=point.qc_point_id,
                qc_point_code=point.qc_point_code,
                name=point.name,
                result="review_required",
                confidence=0.0,
                reason="QC point result not provided by provider",
                evidence={},
            )

    items = [by_id[point.qc_point_id] for point in qc_points]
    item_results = [item.result for item in items]
    if any(item_result == "fail" for item_result in item_results):
        overall = "fail"
    elif any(item_result == "review_required" for item_result in item_results):
        overall = "review_required"
    elif len(items) == len(qc_points) and all(item_result == "pass" for item_result in item_results):
        overall = "pass"
    else:
        overall = "review_required"

    fallback = result.fallback
    summary = result.summary
    if missing_ids and overall == "review_required":
        reason = "provider_output_missing_qc_points"
        fallback = FallbackInfo(used=True, reason=reason)
        summary = summary or "Inspection deferred: provider output was incomplete"

    return result.model_copy(
        update={
            "overall_result": overall,
            "items": items,
            "fallback": fallback,
            "summary": summary,
        }
    )


class QwenRouter:
    """Routes QC inspection requests to available providers.

    This is the backend-side router used for server-side inspection.
    The primary path (on-device) uses the Android router.

    Routing logic:
    1. If simulated_on_device_result="fail" and on_device_fail_is_final → return fail (no cloud)
    2. If cloud_provider is provided and QWEN_CLOUD_ENABLED=true → use cloud
    3. If cloud_provider is provided but cloud disabled → return review_required
    4. If no cloud_provider → return review_required
    """

    def __init__(self, on_device_fail_is_final: bool = True) -> None:
        self.on_device_fail_is_final = on_device_fail_is_final

    def route(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
        cloud_provider: Optional[QwenQCProvider] = None,
        simulated_on_device_result: Optional[str] = None,
    ) -> QwenInspectionOutput:
        """Route inspection to available provider.

        Args:
            standard_photos: Standard reference photos
            captured_photo: Production capture photo
            qc_points: QC criteria to evaluate
            context: Inspection context
            cloud_provider: Optional cloud provider. If None and cloud disabled,
                           returns review_required.

        Returns:
            QwenInspectionOutput
        """
        if not qc_points:
            return _make_review_required(
                qc_points,
                reason="no_detection_points_defined",
                engine="router",
            )

        # §4.5.4: on-device FAIL is final — never escalate to cloud to produce a pass
        if simulated_on_device_result == "fail" and self.on_device_fail_is_final:
            return _make_fail(qc_points, reason="on_device_fail_is_final", engine="router")

        if cloud_provider is None:
            return _make_review_required(
                qc_points,
                reason="no_provider_available",
                engine="router",
            )

        if not _cloud_enabled():
            return _make_review_required(
                qc_points,
                reason="cloud_disabled",
                engine="router",
            )

        try:
            result = cloud_provider.inspect(
                standard_photos=standard_photos,
                captured_photo=captured_photo,
                qc_points=qc_points,
                context=context,
            )
            return _normalize_provider_output(result, qc_points)
        except (RuntimeError, TimeoutError, Exception) as e:
            return _make_review_required(
                qc_points,
                reason=f"provider_error: {type(e).__name__}: {e}",
                engine=getattr(cloud_provider, "engine_name", "cloud_qwen"),
            )
