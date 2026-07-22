"""Pure, deterministic OpenCV analyzers.

Parameters are human-authored starting points.  Accuracy is unmeasured until
the deployment has a representative labeled data set.
"""
from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


def _round(value: float) -> float:
    return round(float(value), 4)


def _box(x: int, y: int, w: int, h: int, width: int, height: int) -> dict[str, float]:
    return {
        "x": _round(x / width),
        "y": _round(y / height),
        "w": _round(w / width),
        "h": _round(h / height),
    }


def _center(x: float, y: float, width: int, height: int) -> dict[str, float]:
    return {"x": _round(x / width), "y": _round(y / height)}


def _contours(mask: np.ndarray) -> list[np.ndarray]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return sorted(contours, key=lambda c: (cv2.boundingRect(c)[1], cv2.boundingRect(c)[0]))


# ─── Metal-armature helpers (socket_holes / pearl_count backends) ───────────
#
# Real-sample audit (2026-07-22): on a prong-set jewelry SKU, the original
# global-threshold blob detectors overcounted badly (11 vs 4 petals, 31/12 vs
# 7 rhinestones) against actual ground truth (STAGE2_QWEN_VISION_PRODUCTION_
# ASSESSMENT_20260722: administrator-confirmed 4 petals / 3 pearls /
# 7 rhinestones on this sample; an earlier pass had mistakenly logged 5
# petals before the assessment's manual recount). A metal setting's wire has a
# reliably distinct warm gold/rose-gold hue independent of the mounted
# stones' own color or the material's translucency, so anchoring detection to
# that mask — rather than to petal/background brightness or saturation, which
# vary a great deal with lighting and material finish — is far more robust
# for this class of SKU. Prong-set stones (rhinestones here) are fully
# enclosed by the wire loop and show up as topological holes in the armature
# mask; flush-set stones (pearls here) are not enclosed and need a separate
# brightness search restricted to the armature's neighborhood.
#
# These parameters are pixel-space, calibrated against a photo whose subject
# has been cropped to its bounding box and normalized to
# ``working_size_px`` on its longest side (see ``_normalize_to_working_size``)
# — this makes the pixel-space defaults consistent across differently-sized
# source photos of the same physical scale of subject, without requiring a
# fragile re-derivation into fractional/relative units. As with every
# analyzer in this module, defaults are a starting point for a specific SKU
# class (mounted-stone jewelry on a uniform dark background); they are not a
# universal calibration and remain informational-only.


class _NormalizedCrop:
    """A subject crop resized to a fixed working scale, with the mapping
    needed to translate its pixel coordinates back into the original image's
    normalized [0,1] coordinate space."""

    def __init__(self, image: np.ndarray, offset: tuple[int, int], scale: float, original_shape: tuple[int, int]):
        self.image = image
        self.offset_x, self.offset_y = offset
        self.scale = scale
        self.original_height, self.original_width = original_shape

    def to_original_xy(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.offset_x + x / self.scale,
            self.offset_y + y / self.scale,
        )

    def center(self, x: float, y: float) -> dict[str, float]:
        ox, oy = self.to_original_xy(x, y)
        return _center(ox, oy, self.original_width, self.original_height)

    def box(self, x: int, y: int, w: int, h: int) -> dict[str, float]:
        ox, oy = self.to_original_xy(x, y)
        return _box(int(round(ox)), int(round(oy)), int(round(w / self.scale)), int(round(h / self.scale)),
                    self.original_width, self.original_height)


def _normalize_to_working_size(image: np.ndarray, params: dict[str, Any]) -> _NormalizedCrop | None:
    """Crop to the subject's bounding box against a uniform dark background,
    then resize so its longest side is ``working_size_px``.

    Assumes the standard-photo capture convention of a single bright subject
    on a materially darker, roughly uniform backdrop (the flower/jewelry
    fixtures used to calibrate this module). Returns ``None`` when no
    foreground region is found (e.g. a blank or inverted-contrast frame) so
    callers fail closed rather than analyzing noise.
    """
    working = int(params.get("working_size_px", 1600))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel_size = max(3, int(round(0.005 * math.hypot(height, width))) | 1)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    outer = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(outer)
    if w == 0 or h == 0:
        return None
    crop = image[y : y + h, x : x + w]
    scale = working / max(crop.shape[0], crop.shape[1])
    resized = cv2.resize(
        crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return _NormalizedCrop(resized, (x, y), scale, (height, width))


def _gold_armature_mask(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any] | None:
    """Isolate the largest connected gold/rose-gold metal region.

    Returns ``None`` when no metal-colored region is found, so callers fail
    closed instead of treating an empty mask as "zero stones found."
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower = np.array(params.get("gold_hsv_lower", [5, 60, 80]), dtype=np.uint8)
    upper = np.array(params.get("gold_hsv_upper", [35, 255, 255]), dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    kernel_size = max(1, int(params.get("armature_close_kernel_px", 11)))
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, kernel, iterations=int(params.get("armature_close_iterations", 3))
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_label = 1 + int(np.argmax(areas))
    armature = np.uint8(labels == largest_label) * 255
    x, y, w, h, area = stats[largest_label]
    return {"mask": armature, "bbox": (int(x), int(y), int(w), int(h)), "area": int(area)}


def rhinestone_count(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Locate bright specular blobs, circles (``backend=hough``), or
    prong-set stones via the metal armature's socket holes
    (``backend=socket_holes`` — see the module docstring block above;
    validated against a real 7-rhinestone sample where the ``contour`` and
    ``hough`` backends overcounted by 4-40x on frosted/reflective material)."""
    if str(params.get("backend", "contour")) == "socket_holes":
        return _rhinestone_count_socket_holes(image, params)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    backend = str(params.get("backend", "contour"))
    min_radius = max(1, int(params.get("min_radius_px", 3)))
    max_radius = max(min_radius, int(params.get("max_radius_px", 24)))
    detections: list[tuple[float, float, float, int, int, int, int]] = []
    if backend == "hough":
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=float(params.get("dp", 1.0)),
            minDist=float(params.get("min_distance_px", min_radius * 2)),
            param1=float(params.get("edge_threshold", 100)),
            param2=float(params.get("accumulator_threshold", 12)),
            minRadius=min_radius,
            maxRadius=max_radius,
        )
        for cx, cy, radius in ([] if circles is None else circles[0]):
            x = max(0, int(round(cx - radius)))
            y = max(0, int(round(cy - radius)))
            w = min(width - x, int(round(radius * 2)))
            h = min(height - y, int(round(radius * 2)))
            detections.append((float(cx), float(cy), float(radius), x, y, w, h))
    elif backend == "contour":
        threshold = int(params.get("highlight_threshold", 220))
        _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        kernel_size = max(1, int(params.get("morphology_kernel_px", 3)))
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        min_area = float(params.get("min_area_px", math.pi * min_radius * min_radius * 0.35))
        max_area = float(params.get("max_area_px", math.pi * max_radius * max_radius * 1.5))
        min_circularity = float(params.get("min_circularity", 0.35))
        for contour in _contours(mask):
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            circularity = 0.0 if perimeter == 0 else 4 * math.pi * area / (perimeter * perimeter)
            if not (min_area <= area <= max_area and circularity >= min_circularity):
                continue
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            x, y, w, h = cv2.boundingRect(contour)
            detections.append((cx, cy, radius, x, y, w, h))
    else:
        raise ValueError(f"unsupported rhinestone_count backend: {backend}")
    detections.sort(key=lambda value: (round(value[1], 4), round(value[0], 4)))
    fill = min(1.0, sum(math.pi * d[2] * d[2] for d in detections) / max(1, width * height))
    confidence = 0.0 if not detections else min(0.99, 0.55 + fill * 8 + min(len(detections), 20) * 0.01)
    return {
        "analyzer": "rhinestone_count",
        "backend": backend,
        "count": len(detections),
        "centers": [_center(d[0], d[1], width, height) for d in detections],
        "boxes": [_box(d[3], d[4], d[5], d[6], width, height) for d in detections],
        "confidence": _round(confidence),
    }


def _empty_rhinestone_result(backend: str) -> dict[str, Any]:
    return {
        "analyzer": "rhinestone_count", "backend": backend, "count": 0,
        "centers": [], "boxes": [], "confidence": 0.0,
    }


def _rhinestone_count_socket_holes(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Count prong-set stones as topological holes in the metal armature.

    A stone held by a full 4-prong loop shows up as a region of background
    (or the stone itself, since clear stones don't register as metal-colored)
    fully enclosed by the gold mask. This is far more robust than a global
    brightness/specular threshold on frosted or reflective material, because
    it keys off the setting's wire, not the stone's own appearance.
    """
    normalized = _normalize_to_working_size(image, params)
    if normalized is None:
        return _empty_rhinestone_result("socket_holes")
    armature = _gold_armature_mask(normalized.image, params)
    if armature is None:
        return _empty_rhinestone_result("socket_holes")
    min_hole_area = float(params.get("min_hole_area_px", 3500))
    contours, hierarchy = cv2.findContours(armature["mask"], cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    detections = []
    for index, contour in enumerate(contours):
        if hierarchy[0][index][3] == -1:  # outer boundary, not an enclosed hole
            continue
        area = cv2.contourArea(contour)
        if area < min_hole_area:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        x, y, w, h = cv2.boundingRect(contour)
        detections.append((area, cx, cy, radius, x, y, w, h))
    detections.sort(key=lambda d: (round(d[2], 1), round(d[1], 1)))
    confidence = 0.0 if not detections else min(0.95, 0.5 + min(len(detections), 15) * 0.03)
    return {
        "analyzer": "rhinestone_count",
        "backend": "socket_holes",
        "count": len(detections),
        "centers": [normalized.center(d[1], d[2]) for d in detections],
        "boxes": [normalized.box(d[4], d[5], d[6], d[7]) for d in detections],
        "confidence": _round(confidence),
    }


def pearl_count(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Count flush-set stones (e.g. pearls) that sit near, but are not
    enclosed by, the metal armature — see the module docstring block above.

    Unlike prong-set stones, these are not topologically enclosed holes, so
    they are found by a brightness search restricted to a neighborhood
    around the armature and explicitly excluding the armature's own metal
    pixels. Distinguishing them from a much smaller prong-set stone is by
    size (``min_area_px``), calibrated to be well above a socket-hole's area
    and well below petal-texture speckle noise.
    """
    normalized = _normalize_to_working_size(image, params)
    if normalized is None:
        return {"analyzer": "pearl_count", "count": 0, "centers": [], "boxes": [], "confidence": 0.0}
    armature = _gold_armature_mask(normalized.image, params)
    if armature is None:
        return {"analyzer": "pearl_count", "count": 0, "centers": [], "boxes": [], "confidence": 0.0}
    x, y, w, h = armature["bbox"]
    cx, cy = x + w / 2, y + h / 2
    search_radius = float(params.get("search_radius_fraction", 0.85)) * math.hypot(w, h) / 2
    search_mask = np.zeros(normalized.image.shape[:2], np.uint8)
    cv2.circle(search_mask, (int(cx), int(cy)), max(1, int(search_radius)), 255, -1)

    gray = cv2.cvtColor(normalized.image, cv2.COLOR_BGR2GRAY)
    threshold = int(params.get("brightness_threshold", 195))
    _, bright = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    region = cv2.bitwise_and(bright, search_mask)
    region = cv2.bitwise_and(region, cv2.bitwise_not(armature["mask"]))
    open_kernel = max(1, int(params.get("open_kernel_px", 9)))
    close_kernel = max(1, int(params.get("close_kernel_px", 25)))
    region = cv2.morphologyEx(region, cv2.MORPH_OPEN, np.ones((open_kernel, open_kernel), np.uint8))
    region = cv2.morphologyEx(region, cv2.MORPH_CLOSE, np.ones((close_kernel, close_kernel), np.uint8))

    min_area = float(params.get("min_area_px", 11100))
    detections = []
    for contour in _contours(region):
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        (ccx, ccy), radius = cv2.minEnclosingCircle(contour)
        bx, by, bw, bh = cv2.boundingRect(contour)
        detections.append((area, ccx, ccy, radius, bx, by, bw, bh))
    detections.sort(key=lambda d: (round(d[2], 1), round(d[1], 1)))
    confidence = 0.0 if not detections else min(0.9, 0.5 + min(len(detections), 10) * 0.04)
    return {
        "analyzer": "pearl_count",
        "count": len(detections),
        "centers": [normalized.center(d[1], d[2]) for d in detections],
        "boxes": [normalized.box(d[4], d[5], d[6], d[7]) for d in detections],
        "confidence": _round(confidence),
    }


def _petal_count_silhouette(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Count petal lobes from the subject's outer silhouette via convexity
    defects, rather than color/saturation masking.

    Real-sample audit (2026-07-22): HSV-saturation masking assumes a
    materially saturated petal color; it cannot discriminate a white or
    translucent/frosted petal from equally-desaturated background noise,
    which is exactly what produced a 138-region false count on a real photo.
    Segmenting the whole bright subject from a dark background first (which
    is robust regardless of petal color or translucency) and then counting
    convex lobes around its outline is far more robust for this material
    class. Validated against the committed real-sample fixture: exact match
    against the administrator-confirmed ground truth of 4 petals
    (STAGE2_QWEN_VISION_PRODUCTION_ASSESSMENT_20260722).

    Known limitation: a petal that is fully occluded by, or tucked behind,
    another petal from the capture angle would produce no silhouette notch
    and be undercounted — this is a genuine limit of single-frame 2D
    silhouette analysis, not a parameter to tune away, even though it did
    not occur on the validated sample. Per the production assessment, CV is
    the counting authority and the vision model may only confirm or dispute
    this count — it must never substitute its own freely generated tally.
    """
    normalized = _normalize_to_working_size(image, params)
    if normalized is None:
        return {"analyzer": "petal_segmentation", "backend": "silhouette", "count": 0,
                "polygons": [], "area_fractions": [], "confidence": 0.0}
    gray = cv2.cvtColor(normalized.image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel_size = max(1, int(params.get("morphology_kernel_px", 15)))
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return {"analyzer": "petal_segmentation", "backend": "silhouette", "count": 0,
                "polygons": [], "area_fractions": [], "confidence": 0.0}
    outer = max(contours, key=cv2.contourArea)
    epsilon = float(params.get("polygon_epsilon", 0.002)) * cv2.arcLength(outer, True)
    approx = cv2.approxPolyDP(outer, epsilon, True)
    hull_indices = cv2.convexHull(approx, returnPoints=False)
    if hull_indices is None or len(hull_indices) < 3:
        return {"analyzer": "petal_segmentation", "backend": "silhouette", "count": 0,
                "polygons": [], "area_fractions": [], "confidence": 0.0}
    hull_indices = sorted(set(int(i) for i in hull_indices.flatten()))
    defects = cv2.convexityDefects(approx, np.array(hull_indices))
    min_depth = float(params.get("min_notch_depth_px", 100))
    lobe_points: list[tuple[int, int]] = []
    if defects is not None:
        for start, end, far, depth in defects.reshape(-1, 4):
            if depth / 256.0 >= min_depth:
                lobe_points.append(tuple(int(v) for v in approx[far][0]))
    count = len(lobe_points)
    area_fraction = _round(cv2.contourArea(outer) / (normalized.image.shape[0] * normalized.image.shape[1]))
    return {
        "analyzer": "petal_segmentation",
        "backend": "silhouette",
        "count": count,
        "polygons": [],
        "notch_points": [normalized.center(x, y) for x, y in lobe_points],
        "area_fractions": [area_fraction] if count else [],
        "confidence": _round(0.0 if not count else min(0.9, 0.5 + count * 0.05)),
    }


def petal_segmentation(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Segment saturated/color-bounded petal regions into polygons, or count
    outer-silhouette lobes when ``backend=silhouette`` (see
    ``_petal_count_silhouette`` — the recommended backend for white or
    translucent petals, where saturation masking cannot discriminate the
    petal from background noise)."""
    if str(params.get("backend", "hsv")) == "silhouette":
        return _petal_count_silhouette(image, params)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower = np.array(params.get("hsv_lower", [0, 70, 40]), dtype=np.uint8)
    upper = np.array(params.get("hsv_upper", [179, 255, 255]), dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    kernel_size = max(1, int(params.get("morphology_kernel_px", 3)))
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    height, width = mask.shape
    min_area = float(params.get("min_area_px", 30))
    polygons: list[list[dict[str, float]]] = []
    areas: list[float] = []
    for contour in _contours(mask):
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        epsilon = float(params.get("polygon_epsilon", 0.02)) * cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, epsilon, True)
        polygons.append([_center(p[0][0], p[0][1], width, height) for p in polygon])
        areas.append(_round(area / (width * height)))
    coverage = sum(areas)
    return {
        "analyzer": "petal_segmentation",
        "count": len(polygons),
        "polygons": polygons,
        "area_fractions": areas,
        "confidence": _round(0.0 if not polygons else min(0.99, 0.55 + coverage)),
    }


def pistil_localization(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Locate the largest authored color range, normally the central pistil."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower = np.array(params.get("hsv_lower", [15, 80, 80]), dtype=np.uint8)
    upper = np.array(params.get("hsv_upper", [45, 255, 255]), dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    height, width = mask.shape
    candidates = [c for c in _contours(mask) if cv2.contourArea(c) >= float(params.get("min_area_px", 20))]
    if not candidates:
        return {
            "analyzer": "pistil_localization",
            "found": False,
            "center": None,
            "box": None,
            "confidence": 0.0,
        }
    contour = max(candidates, key=cv2.contourArea)
    moments = cv2.moments(contour)
    x, y, w, h = cv2.boundingRect(contour)
    cx = x + w / 2 if moments["m00"] == 0 else moments["m10"] / moments["m00"]
    cy = y + h / 2 if moments["m00"] == 0 else moments["m01"] / moments["m00"]
    area_fraction = cv2.contourArea(contour) / (width * height)
    return {
        "analyzer": "pistil_localization",
        "found": True,
        "center": _center(cx, cy, width, height),
        "box": _box(x, y, w, h, width, height),
        "confidence": _round(min(0.99, 0.6 + area_fraction * 4)),
    }
