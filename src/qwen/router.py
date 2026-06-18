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


class QwenRouter:
    """Routes QC inspection requests to available providers.

    This is the backend-side router used for server-side inspection.
    The primary path (on-device) uses the Android router.

    Routing logic:
    1. If cloud_provider is provided and QWEN_CLOUD_ENABLED=true → use cloud
    2. If cloud_provider is provided but cloud disabled → return review_required
    3. If no cloud_provider → return review_required
    """

    def route(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
        cloud_provider: Optional[QwenQCProvider] = None,
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
            return result
        except (RuntimeError, TimeoutError, Exception) as e:
            return _make_review_required(
                qc_points,
                reason=f"provider_error: {type(e).__name__}: {e}",
                engine=getattr(cloud_provider, "engine_name", "cloud_qwen"),
            )
