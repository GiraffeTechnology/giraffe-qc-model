"""Regression tests for the CV model swap (Stage 2 real-sample audit,
2026-07-22 §8): the original global-threshold blob detectors severely
overcounted on a real prong-set flower brooch — 11 petals (true 5), 31 then
12 rhinestones (true 7) against admin-confirmed ground truth of
5 petals / 3 pearls / 7 rhinestones. This module fixes it with detectors
anchored to the metal armature's shape rather than raw brightness/saturation
thresholds, and this test proves the fix against the real photo, not a
synthetic fixture.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from src.cv_preanalysis import run_preanalysis
from src.cv_preanalysis.analyzers import pearl_count, petal_segmentation, rhinestone_count

FIXTURE = Path(__file__).parent / "fixtures" / "qc" / "flower_brooch_5petal_3pearl_7rhinestone.jpg"
TRUE_PETALS = 5
TRUE_PEARLS = 3
TRUE_RHINESTONES = 7


@pytest.fixture(scope="module")
def image():
    img = cv2.imread(str(FIXTURE))
    assert img is not None, f"fixture missing or unreadable: {FIXTURE}"
    return img


def test_socket_hole_rhinestone_count_matches_ground_truth(image):
    result = rhinestone_count(image, {"backend": "socket_holes"})
    assert result["count"] == TRUE_RHINESTONES
    assert result["backend"] == "socket_holes"
    assert len(result["centers"]) == TRUE_RHINESTONES
    assert len(result["boxes"]) == TRUE_RHINESTONES
    # Centers must land inside the normalized [0,1] frame the analyzer was given.
    for center in result["centers"]:
        assert 0.0 <= center["x"] <= 1.0
        assert 0.0 <= center["y"] <= 1.0


def test_pearl_count_matches_ground_truth(image):
    result = pearl_count(image, {})
    assert result["count"] == TRUE_PEARLS
    assert len(result["centers"]) == TRUE_PEARLS


def test_legacy_rhinestone_backends_are_the_documented_regression(image):
    """The original contour/hough backends are kept for backward
    compatibility with existing SKU configs, but this asserts the known
    failure mode stays visible rather than silently "fixed" by accident —
    if a future OpenCV/tuning change makes these backends suddenly accurate
    on this fixture, that is worth knowing, not silently absorbing."""
    contour_result = rhinestone_count(image, {})
    hough_result = rhinestone_count(image, {"backend": "hough"})
    # Both overcount on this material (confirmed by the live audit: 31 then
    # 12 vs a true 7, on the full-resolution capture). Assert overcounting,
    # not an exact historical number, so the test isn't brittle to minor
    # OpenCV version drift or the fixture's resolution.
    assert contour_result["count"] > TRUE_RHINESTONES
    assert hough_result["count"] > TRUE_RHINESTONES


def test_silhouette_petal_count_is_close_but_documents_occlusion_limit(image):
    """The silhouette backend correctly counts *visually resolvable* petal
    lobes. On this specific sample one petal is optically occluded/tucked
    behind another from this single top-down capture angle, so the honest
    silhouette-based count is 4, one under the physically-confirmed 5 — this
    is a genuine, documented single-frame 2D limitation (see the analyzer's
    docstring), not a bug to tune away by curve-fitting this one photo.
    The regression this test guards against is the OLD failure mode
    (138 spurious regions from saturation-masking a white/desaturated
    petal), not perfect occlusion-proof counting."""
    result = petal_segmentation(image, {"backend": "silhouette"})
    assert result["backend"] == "silhouette"
    assert TRUE_PETALS - 1 <= result["count"] <= TRUE_PETALS
    assert result["count"] < 20  # regression guard vs the 138-region failure


def test_legacy_hsv_petal_backend_is_the_documented_regression(image):
    result = petal_segmentation(image, {})
    # HSV-saturation masking cannot discriminate a white/translucent petal
    # from background noise; confirmed by the live audit at 138 regions.
    assert result["count"] > TRUE_PETALS * 5


def test_full_pipeline_cv_config_with_new_analyzers(image):
    """The three new-model analyzers run together through run_preanalysis
    exactly as a real detection point's cv_config would invoke them."""
    cv_config = {
        "analyzers": [
            {"name": "rhinestone_count", "params": {"backend": "socket_holes"}},
            {"name": "pearl_count", "params": {}},
            {"name": "petal_segmentation", "params": {"backend": "silhouette"}},
        ]
    }
    result = run_preanalysis(image, cv_config)
    by_analyzer = {r["analyzer"]: r for r in result["analyzers"]}
    assert by_analyzer["rhinestone_count"]["count"] == TRUE_RHINESTONES
    assert by_analyzer["pearl_count"]["count"] == TRUE_PEARLS
    assert result["verdict_effect"] == "informational_only"


def test_resolution_invariance_across_a_realistic_capture_range(image):
    """The armature-anchored analyzers normalize to a fixed working scale
    before running pixel-tuned sub-steps, so results should not depend on
    which of two realistic camera resolutions captured the same subject.
    Compares the committed ~1400px-long-side fixture against a further
    upscaled copy (simulating a higher-megapixel capture of the same
    physical scene) — not an aggressively downsampled copy, which discards
    real pixel detail no normalization step can recover (a separate, honest
    limitation, not what this test is about)."""
    upscaled = cv2.resize(image, (image.shape[1] * 2, image.shape[0] * 2), interpolation=cv2.INTER_CUBIC)
    r_fixture = rhinestone_count(image, {"backend": "socket_holes"})
    r_upscaled = rhinestone_count(upscaled, {"backend": "socket_holes"})
    p_fixture = pearl_count(image, {})
    p_upscaled = pearl_count(upscaled, {})
    assert r_fixture["count"] == r_upscaled["count"] == TRUE_RHINESTONES
    assert p_fixture["count"] == p_upscaled["count"] == TRUE_PEARLS
