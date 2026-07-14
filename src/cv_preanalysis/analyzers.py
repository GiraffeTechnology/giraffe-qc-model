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


def rhinestone_count(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Locate bright specular blobs, or circles when ``backend=hough``."""
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


def petal_segmentation(image: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Segment saturated/color-bounded petal regions into polygons."""
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
