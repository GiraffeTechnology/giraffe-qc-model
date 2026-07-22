"""Standard-photo to captured-image registration via keypoint matching.

STAGE2_OPEN_SOURCE_CV_EVALUATION_20260722: the per-material armature/
silhouette counters in analyzers.py are accurate on the one photo they were
tuned against but collapse under realistic capture variation — rotation,
exposure, blur, and especially a background that violates their fixed
dark-background assumption (the correct production capture rig uses a green
background; a 50-trial-per-category perturbation benchmark measured single-
digit-to-low-percent precision on rhinestones/pearls under most variation
categories). ORB/SIFT registration against the admin's standard photo scored
100% synthetic-perturbation registration success in the same evaluation and
does not depend on any background assumption at all, since it matches local
keypoint features rather than segmenting a subject from a background.

This module estimates a homography from the standard photo to a newly
captured image and uses it to map each detection point's admin-authored
region (drawn on the standard photo, see src/qc_model/studio/regions.py)
onto the captured image, so the existing counters run against a stable,
correctly-located crop instead of an unlocated full frame. Registration
failure is a hard stop (``RegistrationError``) — callers must never fall
back to running an analyzer on the full, unlocated frame, since an
unverified guess is worse than an explicit "could not locate" signal that
routes to human review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

_BACKENDS = frozenset({"orb", "sift"})


class RegistrationError(RuntimeError):
    """Registration could not be established with sufficient confidence."""


@dataclass(frozen=True)
class RegistrationResult:
    #: 3x3 homography mapping standard-photo pixel coordinates to
    #: captured-image pixel coordinates.
    homography: np.ndarray
    inlier_count: int
    match_count: int
    backend: str


def _detector(backend: str):
    if backend == "orb":
        return cv2.ORB_create(nfeatures=2000)
    if backend == "sift":
        return cv2.SIFT_create()
    raise ValueError(f"unsupported registration backend: {backend!r}; expected one of {sorted(_BACKENDS)}")


def _matcher(backend: str) -> cv2.BFMatcher:
    norm = cv2.NORM_HAMMING if backend == "orb" else cv2.NORM_L2
    return cv2.BFMatcher(norm)


def register(
    standard_image: np.ndarray,
    captured_image: np.ndarray,
    *,
    backend: str = "orb",
    ratio_threshold: float = 0.75,
    min_matches: int = 8,
    min_inliers: int = 10,
    ransac_reproj_threshold: float = 5.0,
) -> RegistrationResult:
    """Estimate a homography from ``standard_image`` to ``captured_image``.

    Raises :class:`RegistrationError` (fail closed) rather than returning a
    low-confidence result — a caller that cannot tell a good homography from
    a bad one must not use one at all.
    """
    if backend not in _BACKENDS:
        raise ValueError(f"unsupported registration backend: {backend!r}; expected one of {sorted(_BACKENDS)}")
    detector = _detector(backend)
    std_gray = cv2.cvtColor(standard_image, cv2.COLOR_BGR2GRAY)
    cap_gray = cv2.cvtColor(captured_image, cv2.COLOR_BGR2GRAY)
    kp1, des1 = detector.detectAndCompute(std_gray, None)
    kp2, des2 = detector.detectAndCompute(cap_gray, None)
    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        raise RegistrationError("insufficient_keypoints")

    raw_matches = _matcher(backend).knnMatch(des1, des2, k=2)
    good = [m for m, n in raw_matches if m.distance < ratio_threshold * n.distance]
    if len(good) < min_matches:
        raise RegistrationError(f"insufficient_matches:{len(good)}")

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, ransac_reproj_threshold)
    if homography is None:
        raise RegistrationError("homography_estimation_failed")
    inlier_count = int(mask.sum()) if mask is not None else 0
    if inlier_count < min_inliers:
        raise RegistrationError(f"insufficient_inliers:{inlier_count}")
    return RegistrationResult(
        homography=homography,
        inlier_count=inlier_count,
        match_count=len(good),
        backend=backend,
    )


def map_region(
    region: dict[str, float],
    homography: np.ndarray,
    *,
    standard_shape: tuple[int, int],
    captured_shape: tuple[int, int],
) -> dict[str, float] | None:
    """Map a normalized ``{x,y,w,h}`` region on the standard photo onto the
    captured image's normalized ``[0,1]`` frame.

    Transforms all four corners (not just the top-left and size) since a
    homography can rotate or skew a rectangle into a general quadrilateral;
    returns that quadrilateral's axis-aligned bounding box, clipped to the
    captured frame. Returns ``None`` if the mapped box collapses (maps
    entirely outside the frame or to zero area) rather than an invalid box.
    """
    std_h, std_w = standard_shape
    cap_h, cap_w = captured_shape
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    corners = np.float32([
        [x * std_w, y * std_h],
        [(x + w) * std_w, y * std_h],
        [(x + w) * std_w, (y + h) * std_h],
        [x * std_w, (y + h) * std_h],
    ]).reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
    xs = mapped[:, 0] / cap_w
    ys = mapped[:, 1] / cap_h
    x0, x1 = max(0.0, float(xs.min())), min(1.0, float(xs.max()))
    y0, y1 = max(0.0, float(ys.min())), min(1.0, float(ys.max()))
    if x1 - x0 <= 0.0 or y1 - y0 <= 0.0:
        return None
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def crop_region(image: np.ndarray, region: dict[str, float]) -> np.ndarray | None:
    """Crop a normalized ``{x,y,w,h}`` region out of ``image``.

    Returns ``None`` for a degenerate crop (zero or negative area) instead
    of a fake 1-pixel-wide array, so callers can treat "no usable crop" as
    one explicit case.
    """
    if region["w"] <= 0.0 or region["h"] <= 0.0:
        return None
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(round(region["x"] * width))))
    y1 = max(0, min(height - 1, int(round(region["y"] * height))))
    x2 = max(x1 + 1, min(width, int(round((region["x"] + region["w"]) * width))))
    y2 = max(y1 + 1, min(height, int(round((region["y"] + region["h"]) * height))))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return crop


def register_and_map_regions(
    standard_image: np.ndarray,
    captured_image: np.ndarray,
    regions_by_point: dict[str, list[dict[str, float]]],
    *,
    backend: str = "orb",
) -> tuple[RegistrationResult, dict[str, list[dict[str, float]]]]:
    """Register once, then map every point's regions with the same homography.

    Raises :class:`RegistrationError` if registration itself fails; a point
    whose individual region collapses under the mapping (see
    :func:`map_region`) is simply omitted from the returned dict rather than
    failing the whole batch, since other points may still be usable.
    """
    result = register(standard_image, captured_image, backend=backend)
    standard_shape = standard_image.shape[:2]
    captured_shape = captured_image.shape[:2]
    mapped: dict[str, list[dict[str, float]]] = {}
    for point_code, regions in regions_by_point.items():
        point_mapped = []
        for region in regions:
            box = map_region(
                region, result.homography,
                standard_shape=standard_shape, captured_shape=captured_shape,
            )
            if box is not None:
                point_mapped.append(box)
        if point_mapped:
            mapped[point_code] = point_mapped
    return result, mapped


__all__ = [
    "RegistrationError",
    "RegistrationResult",
    "register",
    "map_region",
    "crop_region",
    "register_and_map_regions",
]
