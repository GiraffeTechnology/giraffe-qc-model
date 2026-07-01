"""Inspection execution runner (PRD §14).

Orchestrates: preconditions → provider call → deterministic finalization →
lifecycle output policy. The runner depends only on the provider *abstraction*
and the registry — never on a vendor class — so the provider is swappable by
config.

Fail-closed everywhere: any precondition failure, provider error, or invalid
output yields ``review_required`` (never a pass).
"""
from __future__ import annotations

from typing import Optional

from src.qc_model.capture_quality import evaluate_capture_quality
from src.qc_model.finalizer import finalize
from src.qc_model.lifecycle import (
    apply_lifecycle_policy,
    can_inspect,
    not_inspectable_reason,
)
from src.qc_model.providers.base import (
    VisionLanguageModelProvider,
    VisualInspectionRequest,
)
from src.qc_model.providers.registry import get_provider_for_profile
from src.qc_model.runtime_profiles import RuntimeProfile, get_runtime_profile
from src.qc_model.schemas.digital_inspector import DigitalInspector
from src.qc_model.schemas.inspection import (
    CaptureQuality,
    CheckpointResult,
    InspectionRequest,
    InspectionResult,
)
from src.qc_model.schemas.training_pack import TrainingPack


def _review_required(
    request: InspectionRequest,
    pack: Optional[TrainingPack],
    reason: str,
) -> InspectionResult:
    points = pack.confirmed_detection_points() if pack else []
    return InspectionResult(
        inspection_id=request.inspection_id,
        overall_result="review_required",
        training_pack_id=request.training_pack_id,
        playbook_version=request.playbook_version,
        checkpoint_results=[
            CheckpointResult(
                code=dp.code,
                checkpoint_category=dp.confirmed_checkpoint_category or dp.proposed_checkpoint_category,
                result="review_required",
                severity=dp.severity,
                requires_human_review=True,
                finalization_note=reason,
            )
            for dp in points
        ],
        capture_quality=CaptureQuality(acceptable=False, issues=[reason]),
        finalization_rule_applied=reason,
        requires_human_review=True,
    )


def check_preconditions(
    request: InspectionRequest,
    pack: TrainingPack,
    inspector: DigitalInspector,
) -> Optional[str]:
    """Return a failure reason string, or None if all preconditions pass."""
    if pack is None:
        return "precondition_no_training_pack"
    if pack.playbook is None:
        return "precondition_no_playbook"
    if not pack.detection_points:
        return "precondition_no_detection_points"
    if not pack.confirmed_detection_points():
        return "precondition_no_confirmed_detection_points"
    if not pack.reference_images and not request.reference_image_paths:
        return "precondition_no_reference_image"
    if not request.image_paths:
        return "precondition_no_capture_image"
    if not pack.capture_protocol.is_defined():
        return "precondition_no_capture_protocol"
    if not can_inspect(inspector.status):
        return not_inspectable_reason(inspector.status)
    return None


def run_inspection(
    request: InspectionRequest,
    pack: TrainingPack,
    inspector: DigitalInspector,
    *,
    provider: Optional[VisionLanguageModelProvider] = None,
    profile: Optional[RuntimeProfile] = None,
) -> InspectionResult:
    """Run one inspection end-to-end with fail-closed guarantees."""

    # 1. Preconditions (§14.1).
    reason = check_preconditions(request, pack, inspector)
    if reason is not None:
        return _review_required(request, pack, reason)

    # 2. Resolve runtime profile + provider (provider-agnostic).
    profile = profile or get_runtime_profile(inspector.default_runtime_profile)
    provider = provider or get_provider_for_profile(profile)

    confirmed_points = pack.confirmed_detection_points()

    vlm_request = VisualInspectionRequest(
        sku_id=request.sku_id,
        station_id=request.station_id,
        capture_protocol=pack.capture_protocol.model_dump(),
        reference_image_paths=list(pack.reference_images) + list(request.reference_image_paths),
        inspection_image_paths=list(request.image_paths),
        detection_points=[
            {
                "code": dp.code,
                "name": dp.name,
                "checkpoint_category": dp.confirmed_checkpoint_category,
                "target_region": dp.target_region,
                "normal_visual_features": dp.normal_visual_features,
                "defect_visual_features": dp.defect_visual_features,
                "known_pseudo_defects": dp.known_pseudo_defects,
                "decision_rule": dp.decision_rule,
                "review_required_conditions": dp.review_required_conditions,
            }
            for dp in confirmed_points
        ],
        inspection_context=request.inspection_context,
    )

    # 3. Provider call — never let an exception become a pass.
    try:
        response = provider.inspect(vlm_request)
    except Exception as exc:  # fail closed
        from src.qc_model.providers.base import VisualInspectionResponse

        response = VisualInspectionResponse(
            overall_result="review_required",
            checkpoint_results=[],
            provider=getattr(provider, "provider_name", "unknown"),
            model=getattr(provider, "model_name", "unknown"),
            valid=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    # 4. Capture quality gate.
    capture_quality = evaluate_capture_quality(response.capture_quality)

    # 5. Deterministic finalization (§14.4) — model overall never trusted.
    result = finalize(
        inspection_id=request.inspection_id,
        response=response,
        detection_points=confirmed_points,
        capture_quality=capture_quality,
        runtime_profile=profile.environment.value,
        training_pack_id=request.training_pack_id,
        playbook_version=request.playbook_version,
    )

    # 6. Lifecycle output policy (on_trial / suspended).
    result = apply_lifecycle_policy(inspector.status, result)
    return result
