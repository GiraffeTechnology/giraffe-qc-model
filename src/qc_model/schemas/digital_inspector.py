"""Digital Inspector schema + lifecycle states (PRD §10.4, §11)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class InspectorStatus(str, Enum):
    DRAFT = "draft"
    TRAINING_PACK_PENDING = "training_pack_pending"
    LEARNING = "learning"
    EXAM_READY = "exam_ready"
    EXAM_FAILED = "exam_failed"
    EXAM_PASSED = "exam_passed"
    ON_TRIAL = "on_trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class DigitalInspector(BaseModel):
    """A SKU-specific, workstation-specific digital inspector (PRD §10.4)."""

    inspector_id: str
    factory_id: str
    station_id: str
    sku_id: str
    revision: str = "1"

    default_model_provider: str = "qwen3_5_vl"
    # "server" | "tablet_mnn"
    default_runtime_profile: str = "server"
    # "qwen3.5-vl-8b-int4" | "qwen3.5-vl-2b-mnn"
    default_model_name: str = "qwen3.5-vl-8b-int4"

    training_pack_id: Optional[str] = None
    playbook_version: Optional[str] = None
    status: InspectorStatus = InspectorStatus.DRAFT

    requires_requalification: bool = False
    tenant_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
