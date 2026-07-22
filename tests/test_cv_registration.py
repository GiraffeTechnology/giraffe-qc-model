"""Tests for standard-photo -> captured-image registration
(STAGE2_OPEN_SOURCE_CV_EVALUATION_20260722)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from src.cv_preanalysis.registration import (
    RegistrationError,
    crop_region,
    map_region,
    register,
    register_and_map_regions,
)

FIXTURE = Path(__file__).parent / "fixtures" / "qc" / "flower_brooch_4petal_3pearl_7rhinestone.jpg"


@pytest.fixture(scope="module")
def standard_image():
    img = cv2.imread(str(FIXTURE))
    assert img is not None, f"fixture missing or unreadable: {FIXTURE}"
    return img


def _synthetic_capture(image, *, angle_deg=8.0, scale=0.9, tx=40, ty=-20):
    """Apply a known rotation/scale/translation homography, simulating a
    realistic re-shoot at a slightly different angle/distance/position, and
    return both the warped image and the exact ground-truth homography used
    to produce it (for verifying map_region's accuracy against a known
    answer, not just checking that registration runs without error)."""
    h, w = image.shape[:2]
    center = (w / 2, h / 2)
    rot_scale = cv2.getRotationMatrix2D(center, angle_deg, scale)
    homography = np.vstack([rot_scale, [0, 0, 1]]).astype(np.float64)
    homography[0, 2] += tx
    homography[1, 2] += ty
    captured = cv2.warpPerspective(image, homography, (w, h), borderValue=(30, 60, 30))
    return captured, homography


def test_orb_registration_succeeds_on_rotated_scaled_capture(standard_image):
    captured, _ = _synthetic_capture(standard_image)
    result = register(standard_image, captured, backend="orb")
    assert result.backend == "orb"
    assert result.inlier_count >= 10


def test_sift_registration_succeeds_on_rotated_scaled_capture(standard_image):
    captured, _ = _synthetic_capture(standard_image)
    result = register(standard_image, captured, backend="sift")
    assert result.backend == "sift"
    assert result.inlier_count >= 10


def _iou(a, b):
    ax0, ay0, ax1, ay1 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def test_map_region_matches_ground_truth_transform(standard_image):
    """The estimated homography (from feature matching) must place a
    detection point's region close to where the *known* ground-truth
    transform actually put it -- not just "registration ran without
    error"."""
    captured, ground_truth_h = _synthetic_capture(standard_image)
    result = register(standard_image, captured, backend="orb")
    region = {"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2}
    shapes = dict(standard_shape=standard_image.shape[:2], captured_shape=captured.shape[:2])
    estimated = map_region(region, result.homography, **shapes)
    ground_truth = map_region(region, ground_truth_h, **shapes)
    assert estimated is not None
    assert ground_truth is not None
    assert _iou(estimated, ground_truth) >= 0.85


def test_registration_fails_closed_on_unrelated_images(standard_image):
    noise = np.random.default_rng(0).integers(0, 255, size=standard_image.shape, dtype=np.uint8).astype(np.uint8)
    with pytest.raises(RegistrationError):
        register(standard_image, noise, backend="orb")


def test_registration_rejects_unsupported_backend(standard_image):
    with pytest.raises(ValueError):
        register(standard_image, standard_image, backend="unsupported")


def test_crop_region_returns_none_for_degenerate_region(standard_image):
    assert crop_region(standard_image, {"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0}) is None


def test_crop_region_extracts_expected_pixels(standard_image):
    crop = crop_region(standard_image, {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5})
    h, w = standard_image.shape[:2]
    assert crop is not None
    assert abs(crop.shape[0] - h * 0.5) <= 2
    assert abs(crop.shape[1] - w * 0.5) <= 2


def test_register_and_map_regions_maps_all_points(standard_image):
    captured, _ = _synthetic_capture(standard_image)
    regions_by_point = {
        "RHINESTONE_COUNT": [{"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4}],
        "PEARL_COUNT": [{"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}],
    }
    result, mapped = register_and_map_regions(standard_image, captured, regions_by_point, backend="orb")
    assert result.inlier_count >= 10
    assert set(mapped) == {"RHINESTONE_COUNT", "PEARL_COUNT"}
    for boxes in mapped.values():
        assert len(boxes) == 1


def test_register_and_map_regions_propagates_registration_failure():
    unrelated_a = np.zeros((200, 200, 3), dtype=np.uint8)
    unrelated_b = np.random.default_rng(1).integers(0, 255, size=(200, 200, 3), dtype=np.uint8).astype(np.uint8)
    with pytest.raises(RegistrationError):
        register_and_map_regions(unrelated_a, unrelated_b, {"P": [{"x": 0, "y": 0, "w": 1, "h": 1}]})
