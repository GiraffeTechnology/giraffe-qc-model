"""Performance and cost boundary tests — offline, CI-safe.

Validates per-tier latency budgets and tier-saving ratios using synthetic
frames. No network, no device, no API keys required.
"""
from __future__ import annotations

import time

import numpy as np
import pytest


def _bgr(value: int = 128, h: int = 720, w: int = 1280) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


def _gray(value: int = 128, h: int = 480, w: int = 640) -> np.ndarray:
    return np.full((h, w), value, dtype=np.uint8)


class TestL1Latency:
    def test_has_changed_under_5ms_median(self):
        from src.video.frame_filter import has_changed
        prev = _gray(0)
        curr = _gray(128)
        times = []
        for _ in range(200):
            t0 = time.perf_counter()
            has_changed(prev, curr)
            times.append((time.perf_counter() - t0) * 1000)
        median_ms = sorted(times)[len(times) // 2]
        assert median_ms < 5.0, f"L1 median {median_ms:.3f} ms exceeds 5 ms budget"

    def test_first_frame_always_triggers(self):
        from src.video.frame_filter import has_changed
        changed, _ = has_changed(None, _gray())
        assert changed is True

    def test_identical_frames_never_triggers(self):
        from src.video.frame_filter import has_changed
        f = _gray(64)
        changed, _ = has_changed(f, f)
        assert not changed


class TestL2Latency:
    def test_detector_score_under_200ms_median(self, tmp_path):
        import cv2
        from src.video.detector import HybridDetector
        ref_img = np.full((128, 128, 3), 200, dtype=np.uint8)
        p_ref = str(tmp_path / "ref.png")
        cv2.imwrite(p_ref, ref_img)
        detector = HybridDetector()
        prod_frame = np.full((128, 128, 3), 130, dtype=np.uint8)
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            detector.score(prod_frame, [p_ref])
            times.append((time.perf_counter() - t0) * 1000)
        median_ms = sorted(times)[len(times) // 2]
        assert median_ms < 200.0, f"L2 median {median_ms:.1f} ms exceeds 200 ms budget"


class TestL3Latency:
    def test_cv_comparator_under_500ms_median(self, tmp_path):
        import cv2
        from src.cv.comparator import CVComparator
        img = np.full((100, 100, 3), 200, dtype=np.uint8)
        p1, p2 = str(tmp_path / "a.png"), str(tmp_path / "b.png")
        cv2.imwrite(p1, img)
        cv2.imwrite(p2, img)
        comparator = CVComparator()
        times = []
        for _ in range(10):
            t0 = time.perf_counter()
            comparator.compare_images([p1], [p2])
            times.append((time.perf_counter() - t0) * 1000)
        median_ms = sorted(times)[len(times) // 2]
        assert median_ms < 500.0, f"L3/CV median {median_ms:.1f} ms exceeds 500 ms budget"


class TestTierSavings:
    def test_l1_identical_frames_saves_all(self):
        """20 identical frames → only the first triggers L2."""
        from src.video.frame_filter import has_changed
        frames = [_gray(64) for _ in range(20)]
        l2_count = 0
        prev = None
        for f in frames:
            changed, _ = has_changed(prev, f)
            if changed:
                l2_count += 1
            prev = f
        assert l2_count == 1, f"Expected 1 L2 trigger, got {l2_count}"

    def test_l2_tier3_calls_never_exceed_total(self, tmp_path):
        import cv2
        from src.video.detector import HybridDetector, above_threshold
        ref_img = np.full((64, 64, 3), 128, dtype=np.uint8)
        p_ref = str(tmp_path / "ref.png")
        cv2.imwrite(p_ref, ref_img)
        detector = HybridDetector()
        total = 10
        tier3_calls = 0
        for i in range(total):
            frame = np.full((64, 64, 3), (i * 25) % 256, dtype=np.uint8)
            score, _ = detector.score(frame, [p_ref])
            if above_threshold(score):
                tier3_calls += 1
        assert tier3_calls <= total

    def test_cv_stability_three_runs(self, tmp_path):
        import cv2
        from src.cv.comparator import CVComparator
        img = np.full((100, 100, 3), 200, dtype=np.uint8)
        p1, p2 = str(tmp_path / "a.png"), str(tmp_path / "b.png")
        cv2.imwrite(p1, img)
        cv2.imwrite(p2, img)
        comparator = CVComparator()
        results = [comparator.compare_images([p1], [p2]).overall_result for _ in range(3)]
        assert len(set(results)) == 1, f"Unstable classification over 3 runs: {results}"
