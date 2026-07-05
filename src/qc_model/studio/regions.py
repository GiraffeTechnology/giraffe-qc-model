"""Region annotation validation + persistence (PRD Authoring Extension §2).

A detection point can be spatially grounded on one or more of a SKU's standard
photos by drawing bounding-box *regions*. Each region is a normalized box
``{image_id, x, y, w, h}`` (0–1 coordinates, top-left origin) that references a
:class:`~src.db.sku_models.QCStandardPhoto` belonging to the same SKU.

Rules (fail-closed):
- A point supports **zero, one, or many** regions — an empty list is valid and
  clears any existing annotation.
- ``image_id`` must reference a standard photo of the point's SKU (and tenant).
- ``x, y, w, h`` are floats in ``[0, 1]``; the box must stay inside the image
  (``x + w <= 1`` and ``y + h <= 1``) and have positive area.
- Draw mode is bounding box only; freehand/polygon is out of scope this
  iteration, so only these five keys are accepted.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from src.db.sku_models import QCDetectionPoint, QCStandardPhoto

_REGION_KEYS = ("image_id", "x", "y", "w", "h")
_COORD_KEYS = ("x", "y", "w", "h")


class InvalidRegion(ValueError):
    """A region annotation is malformed or references an unknown photo."""


def normalize_regions(
    regions: List[Dict[str, Any]] | None,
    valid_image_ids: set[str],
) -> List[Dict[str, Any]]:
    """Validate + canonicalize a list of regions against a photo id set.

    Returns a clean list of ``{image_id, x, y, w, h}`` dicts (floats for the
    coordinates). Raises :class:`InvalidRegion` fail-closed on any problem.
    """
    if regions is None:
        return []
    if not isinstance(regions, list):
        raise InvalidRegion("regions must be a list")

    clean: List[Dict[str, Any]] = []
    for i, region in enumerate(regions):
        if not isinstance(region, dict):
            raise InvalidRegion(f"region[{i}] must be an object")
        extra = set(region) - set(_REGION_KEYS)
        if extra:
            raise InvalidRegion(
                f"region[{i}] has unsupported keys {sorted(extra)}; only "
                f"{list(_REGION_KEYS)} are allowed (bounding box only)"
            )
        image_id = region.get("image_id")
        if not image_id or not isinstance(image_id, str):
            raise InvalidRegion(f"region[{i}].image_id is required")
        if image_id not in valid_image_ids:
            raise InvalidRegion(
                f"region[{i}].image_id {image_id!r} is not a standard photo of this SKU"
            )
        coords: Dict[str, float] = {}
        for key in _COORD_KEYS:
            value = region.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidRegion(f"region[{i}].{key} must be a number in [0, 1]")
            value = float(value)
            if not (0.0 <= value <= 1.0):
                raise InvalidRegion(f"region[{i}].{key}={value} is outside [0, 1]")
            coords[key] = value
        if coords["w"] <= 0.0 or coords["h"] <= 0.0:
            raise InvalidRegion(f"region[{i}] must have positive width and height")
        if coords["x"] + coords["w"] > 1.0 + 1e-9 or coords["y"] + coords["h"] > 1.0 + 1e-9:
            raise InvalidRegion(f"region[{i}] extends past the image bounds")
        clean.append({"image_id": image_id, **coords})
    return clean


def set_detection_point_regions(
    db: Session,
    detection_point_id: str,
    regions: List[Dict[str, Any]] | None,
    tenant_id: str = "default",
) -> QCDetectionPoint:
    """Replace the region annotations on a detection point (§2 confirmation step).

    Editing regions never touches the judgment being tested, so callers that
    care about Probation progress should note this is a *preserve* edit (see
    :mod:`src.qc_model.qualification.probation`). Raises :class:`InvalidRegion`
    fail-closed; leaves the row untouched on error.
    """
    dp = (
        db.query(QCDetectionPoint)
        .filter_by(id=detection_point_id, tenant_id=tenant_id)
        .first()
    )
    if dp is None:
        raise InvalidRegion(f"detection point {detection_point_id!r} not found")

    valid_image_ids = {
        pid
        for (pid,) in db.query(QCStandardPhoto.id)
        .filter_by(sku_id=dp.sku_id, tenant_id=tenant_id)
        .all()
    }
    clean = normalize_regions(regions, valid_image_ids)
    dp.regions_json = clean
    db.commit()
    db.refresh(dp)
    return dp


__all__ = ["InvalidRegion", "normalize_regions", "set_detection_point_regions"]
