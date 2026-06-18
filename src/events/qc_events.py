"""Event payload builders for QC inspection events.

Builds structured event payloads for the 5 main QC event types.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_standard_created_event(
    tenant_id: str,
    standard_id: str,
    sku_id: str,
    name: str,
    version: str,
    status: str,
) -> Dict[str, Any]:
    """Build event payload for ProductStandard creation."""
    return {
        "event_type": "qc.standard.created",
        "occurred_at": _utcnow_iso(),
        "tenant_id": tenant_id,
        "payload": {
            "standard_id": standard_id,
            "sku_id": sku_id,
            "name": name,
            "version": version,
            "status": status,
        },
    }


def build_inspection_started_event(
    tenant_id: str,
    inspection_id: str,
    sku_id: str,
    standard_id: str,
    capture_photo_id: str,
) -> Dict[str, Any]:
    """Build event payload for InspectionRun start."""
    return {
        "event_type": "qc.inspection.started",
        "occurred_at": _utcnow_iso(),
        "tenant_id": tenant_id,
        "payload": {
            "inspection_id": inspection_id,
            "sku_id": sku_id,
            "standard_id": standard_id,
            "capture_photo_id": capture_photo_id,
        },
    }


def build_inspection_completed_event(
    tenant_id: str,
    inspection_id: str,
    sku_id: str,
    standard_id: str,
    overall_result: str,
    confidence: float,
    engine: str,
    model_name: str,
    item_count: int,
    fallback_used: bool,
    summary: str,
) -> Dict[str, Any]:
    """Build event payload for InspectionRun completion."""
    return {
        "event_type": "qc.inspection.completed",
        "occurred_at": _utcnow_iso(),
        "tenant_id": tenant_id,
        "payload": {
            "inspection_id": inspection_id,
            "sku_id": sku_id,
            "standard_id": standard_id,
            "overall_result": overall_result,
            "confidence": confidence,
            "engine": engine,
            "model_name": model_name,
            "item_count": item_count,
            "fallback_used": fallback_used,
            "summary": summary,
        },
    }


def build_inspection_failed_event(
    tenant_id: str,
    inspection_id: str,
    sku_id: str,
    standard_id: str,
    error_message: str,
) -> Dict[str, Any]:
    """Build event payload for InspectionRun failure."""
    return {
        "event_type": "qc.inspection.failed",
        "occurred_at": _utcnow_iso(),
        "tenant_id": tenant_id,
        "payload": {
            "inspection_id": inspection_id,
            "sku_id": sku_id,
            "standard_id": standard_id,
            "error_message": error_message,
        },
    }


def build_asset_registered_event(
    tenant_id: str,
    asset_id: str,
    sku_id: str,
    asset_type: str,
    inspection_run_id: Optional[str],
    local_path: str,
    sha256: Optional[str],
    contains_pii: bool,
) -> Dict[str, Any]:
    """Build event payload for QCAsset registration."""
    return {
        "event_type": "qc.asset.registered",
        "occurred_at": _utcnow_iso(),
        "tenant_id": tenant_id,
        "payload": {
            "asset_id": asset_id,
            "sku_id": sku_id,
            "asset_type": asset_type,
            "inspection_run_id": inspection_run_id,
            "local_path": local_path,
            "sha256": sha256,
            "contains_pii": contains_pii,
        },
    }
