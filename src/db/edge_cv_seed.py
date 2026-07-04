"""Seed data for the Edge CV subsystem (§19).

Idempotent: safe to call repeatedly. Seeds a mock runner device, an offline
Jetson Nano 2GB profile, and the mock defect-candidate-detection model so the
full slice can run in dev/CI without any real hardware.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from src.db.models import _utcnow
from src.db.edge_cv_models import EdgeCVDevice, EdgeCVModel

_MOCK_CAPS = [
    "image_preprocess",
    "object_detection",
    "defect_candidate_detection",
    "crop_generation",
    "annotated_image_generation",
]
_JETSON_CAPS = ["opencv"] + _MOCK_CAPS + ["live_candidate_lock_capture"]


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def _get_or_create_device(db: Session, tenant_id: str, name: str, **kwargs) -> EdgeCVDevice:
    existing = db.query(EdgeCVDevice).filter_by(tenant_id=tenant_id, device_name=name).first()
    if existing is not None:
        return existing
    device = EdgeCVDevice(id=_uid("edge_dev_"), tenant_id=tenant_id, device_name=name, **kwargs)
    db.add(device)
    return device


def seed_edge_cv_defaults(db: Session, tenant_id: str = "default") -> None:
    """Seed mock runner, Jetson profile, and mock model (idempotent — §19)."""
    now = _utcnow()

    _get_or_create_device(
        db,
        tenant_id,
        "mock-edge-cv-runner",
        device_type="mock_runner",
        status="online",
        capabilities_json=_MOCK_CAPS,
        max_concurrent_jobs=1,
        last_heartbeat_at=now,
        last_seen_at=now,
        is_enabled=True,
    )

    _get_or_create_device(
        db,
        tenant_id,
        "jetson-nano-2gb-profile",
        device_type="jetson_nano_2gb",
        status="offline",
        capabilities_json=_JETSON_CAPS,
        max_concurrent_jobs=1,
        is_enabled=True,
    )

    existing_model = (
        db.query(EdgeCVModel)
        .filter_by(tenant_id=tenant_id, model_name="mock-defect-candidate-detector")
        .first()
    )
    if existing_model is None:
        db.add(
            EdgeCVModel(
                id=_uid("cv_model_"),
                tenant_id=tenant_id,
                model_name="mock-defect-candidate-detector",
                model_version="0.1.0",
                task_type="defect_candidate_detection",
                model_format="mock",
                artifact_uri="mock://defect-candidate-detector",
                target_device_type="any",
                required_capabilities_json=["defect_candidate_detection"],
                min_memory_mb=256,
                model_hash="mock-hash",
                is_active=True,
            )
        )

    db.commit()
