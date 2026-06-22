"""Schema validation helpers for parsed capability outputs."""
from __future__ import annotations

from typing import Any


def clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def validate_result_literal(value: Any) -> str:
    """Normalize result to pass|fail|review_required. Unknown → review_required."""
    if value in ("pass", "fail", "review_required"):
        return value
    return "review_required"


def validate_bbox(bbox: Any) -> list[float] | None:
    """Validate normalized bbox [x1,y1,x2,y2] in [0,1]. Returns None if invalid."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        coords = [float(c) for c in bbox]
    except (TypeError, ValueError):
        return None
    if all(0.0 <= c <= 1.0 for c in coords):
        return coords
    return None


def reject_hallucinated_ids(items: list[dict], valid_ids: set[str]) -> list[dict]:
    """Remove items whose qc_point_id is not in valid_ids."""
    return [item for item in items if item.get("qc_point_id") in valid_ids]


def fill_missing_ids(items: list[dict], valid_ids: set[str], reason: str = "missing_from_model") -> list[dict]:
    """Add review_required placeholder for any valid_id not in items."""
    present = {item.get("qc_point_id") for item in items}
    extras = []
    for vid in valid_ids:
        if vid not in present:
            extras.append({
                "qc_point_id": vid,
                "qc_point_code": "",
                "name": "",
                "result": "review_required",
                "confidence": 0.0,
                "reason": reason,
                "evidence": {},
            })
    return items + extras
