"""Shared per-detection-point CV evidence pipeline.

Runs classical CV analyzers (src.cv_preanalysis) against a captured image,
using standard-photo registration (src.cv_preanalysis.registration) to
locate an authored region when one exists, so a detection point's CV
evidence comes from a correctly-located crop rather than an unlocated full
frame. Used by both the production vision-analyze endpoint
(src.api.pad_router) and the training-judgment recorder
(src.qc_model.qualification.training) so a training run exercises the same
evidence pipeline a real inspection uses -- a training pass/fail is only
meaningful if it reflects production behavior.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from sqlalchemy.orm import Session

from src.cv_preanalysis import PreanalysisError, run_preanalysis, write_evidence


class RegistrationFailed(RuntimeError):
    """A detection point has an authored region but it could not be mapped
    onto the captured image (missing/unreadable standard photo, or
    registration/mapping failure) -- never falls back to the unlocated full
    frame; see STAGE2_OPEN_SOURCE_CV_EVALUATION_20260722: running CV on a
    full, unlocated frame is exactly the failure mode this guards against.
    """


def read_cv_image(path: Path):
    import cv2
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def load_registration(
    db: Session, tenant_id: str, standard_photo_id: str, captured_image, cache: Dict[str, Any],
):
    """Register the captured image against one standard photo, cached per
    photo id so points sharing a standard photo only pay for it once.
    Returns ``(RegistrationResult, standard_image_shape)`` or ``None`` if
    the photo is missing/unreadable or registration could not be
    established with sufficient confidence."""
    if standard_photo_id in cache:
        return cache[standard_photo_id]
    from src.cv_preanalysis.registration import RegistrationError, register
    from src.db.sku_models import QCStandardPhoto

    result = None
    photo = db.query(QCStandardPhoto).filter_by(id=standard_photo_id, tenant_id=tenant_id).first()
    if photo is not None and photo.local_path and Path(photo.local_path).is_file():
        standard_image = read_cv_image(Path(photo.local_path))
        if standard_image is not None and captured_image is not None:
            try:
                registration = register(standard_image, captured_image, backend="orb")
            except RegistrationError:
                registration = None
            if registration is not None:
                result = (registration, standard_image.shape[:2])
    cache[standard_photo_id] = result
    return result


def registered_crop(db: Session, tenant_id: str, point, captured_image, cache: Dict[str, Any]):
    """Map a detection point's first authored region onto the captured
    image via standard-photo registration and return the cropped ndarray.

    Raises :class:`RegistrationFailed` for every way this can go wrong
    (missing image_id, registration failure, a region that maps outside the
    frame, a degenerate crop) so the caller always has one thing to catch."""
    from src.cv_preanalysis.registration import crop_region, map_region

    region = (point.regions_json or [None])[0]
    standard_photo_id = region.get("image_id") if region else None
    if not standard_photo_id:
        raise RegistrationFailed("region_missing_image_id")
    if captured_image is None:
        raise RegistrationFailed("captured_image_unreadable")
    cached = load_registration(db, tenant_id, standard_photo_id, captured_image, cache)
    if cached is None:
        raise RegistrationFailed("registration_failed")
    registration, standard_shape = cached
    mapped = map_region(
        region, registration.homography,
        standard_shape=standard_shape, captured_shape=captured_image.shape[:2],
    )
    if mapped is None:
        raise RegistrationFailed("region_mapping_collapsed")
    crop = crop_region(captured_image, mapped)
    if crop is None:
        raise RegistrationFailed("region_crop_degenerate")
    return crop


def run_cv_for_points(
    db: Session,
    *,
    tenant_id: str,
    points: list,
    image_path: Path,
    evidence_root: Path,
    request_id: str,
) -> tuple[list[dict], list[dict]]:
    """Run CV evidence collection for every detection point against one
    captured image. Returns ``(cv_records, cv_prompt_points)``:
    ``cv_records`` is the full per-point audit trail (including
    not_configured/failed/registration_failed points); ``cv_prompt_points``
    is the subset with completed analysis, ready to inject into a vision
    prompt as CV context.
    """
    captured_image = read_cv_image(image_path)
    registration_cache: Dict[str, Any] = {}
    cv_records: list[dict[str, Any]] = []
    cv_prompt_points: list[dict[str, Any]] = []
    for point in points:
        config = point.cv_config_json or {}
        if not config:
            cv_records.append({
                "point_code": point.point_code,
                "cv_status": "not_configured",
                "analysis": None,
                "evidence_path": None,
            })
            continue
        analysis_image: Any = image_path
        if point.regions_json:
            try:
                analysis_image = registered_crop(db, tenant_id, point, captured_image, registration_cache)
            except RegistrationFailed as exc:
                cv_records.append({
                    "point_code": point.point_code,
                    "cv_status": "registration_failed",
                    "error": str(exc)[:500],
                    "analysis": None,
                    "evidence_path": None,
                })
                continue
        try:
            analysis = run_preanalysis(analysis_image, config, point.expected_features_json or {})
            evidence_path = write_evidence(
                evidence_root, request_id=request_id, point_code=point.point_code, analysis=analysis,
            )
        except PreanalysisError as exc:
            cv_records.append({
                "point_code": point.point_code,
                "cv_status": "failed",
                "error": str(exc)[:500],
                "analysis": None,
                "evidence_path": None,
            })
            continue
        cv_records.append({
            "point_code": point.point_code,
            "cv_status": "completed",
            "analysis": analysis,
            "evidence_path": evidence_path,
        })
        cv_prompt_points.append({"point_code": point.point_code, "analysis": analysis})
    return cv_records, cv_prompt_points


__all__ = [
    "RegistrationFailed",
    "load_registration",
    "read_cv_image",
    "registered_crop",
    "run_cv_for_points",
]
