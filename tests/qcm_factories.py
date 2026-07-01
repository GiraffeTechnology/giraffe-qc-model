"""Shared factories for qc_model Phase 1 tests (not a test module)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.qc_model.schemas.detection_point import DetectionPoint
from src.qc_model.schemas.digital_inspector import DigitalInspector, InspectorStatus
from src.qc_model.schemas.inspection import InspectionRequest
from src.qc_model.schemas.training_pack import (
    CaptureProtocol,
    Playbook,
    TrainingPack,
    TrainingPackStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_detection_point(
    code: str = "missing_rhinestone",
    category: str = "visual_defect",
    confirmed: bool = True,
    severity: str = "critical",
    evidence_required: bool = True,
) -> DetectionPoint:
    dp = DetectionPoint(
        code=code,
        name=code.replace("_", " ").title(),
        raw_operator_requirement=f"Check {code}.",
        proposed_checkpoint_category=category,
        severity=severity,
        target_region="flower_center",
        normal_visual_features=["stable bright specular highlight"],
        defect_visual_features=["dark hollow position"],
        known_pseudo_defects=["temporary glare"],
        decision_rule="fail if reflective structure missing and not a capture artifact",
        review_required_conditions=["overexposed"],
        evidence_required=evidence_required,
    )
    if confirmed:
        dp = dp.confirm_category(category, "qc_supervisor_1", _now(), "confirmed")
    return dp


def make_training_pack(
    detection_points=None,
    status: TrainingPackStatus = TrainingPackStatus.QUALIFIED,
    with_playbook: bool = True,
    with_reference: bool = True,
    with_capture_protocol: bool = True,
    playbook_questions=None,
) -> TrainingPack:
    if detection_points is None:
        detection_points = [make_detection_point()]
    return TrainingPack(
        training_pack_id="tp1",
        sku_id="sku1",
        station_id="st1",
        status=status,
        playbook=Playbook(version="1", questions_or_ambiguities=playbook_questions or [])
        if with_playbook
        else None,
        capture_protocol=CaptureProtocol(lighting="fixed diffuse white light", required_views=["front"])
        if with_capture_protocol
        else CaptureProtocol(),
        reference_images=["ref_front.png"] if with_reference else [],
        positive_samples=["pos1.png"],
        defect_samples=["def1.png"],
        boundary_samples=["bnd1.png"],
        detection_points=detection_points,
    )


def make_inspector(status: InspectorStatus = InspectorStatus.ACTIVE) -> DigitalInspector:
    return DigitalInspector(
        inspector_id="i1",
        factory_id="f1",
        station_id="st1",
        sku_id="sku1",
        status=status,
        default_runtime_profile="server",
        default_model_name="qwen3.5-vl-8b-int4",
        training_pack_id="tp1",
    )


def make_request() -> InspectionRequest:
    return InspectionRequest(
        inspection_id="ins1",
        sku_id="sku1",
        station_id="st1",
        operator_id="op1",
        training_pack_id="tp1",
        playbook_version="1",
        image_paths=["capture.png"],
    )
