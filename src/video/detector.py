"""
Tier-2: Hybrid local detector (ORB + HSV colour histogram).

Strategy:
  For textured images  → ORB keypoint matching (rotation-/scale-invariant)
  For uniform/coloured → HSV histogram similarity (Bhattacharyya coefficient)
  Final score = max(orb_score, hist_score)

This two-signal approach handles both:
  - Textile products with texture (ORB dominant)
  - Flat-colour or shape-dominant products (histogram dominant)

No LLM involved — fully local CPU computation, ~5ms per frame.

Threshold LOCAL_PREFILTER_THRESHOLD (default 0.25):
  Lower → higher recall, more LLM calls
  Higher → lower recall, fewer LLM calls
"""
from __future__ import annotations
import numpy as np
import cv2

from src.config import local_prefilter_threshold

_MAX_FEATURES = 500


class LocalDetector:
    """Pluggable detector interface — swap algorithm without touching pipeline."""

    def score(self, frame_bgr: np.ndarray, sample_paths: list[str]) -> tuple[float, str | None]:
        """Return (best_score 0.0-1.0, matched_sample_path or None)."""
        raise NotImplementedError


def _hist_score(img1_bgr: np.ndarray, img2_bgr: np.ndarray) -> float:
    """
    Bhattacharyya-based HSV histogram similarity.
    Returns 1.0 for identical histograms, 0.0 for completely different.
    """
    h1 = cv2.calcHist(
        [cv2.cvtColor(img1_bgr, cv2.COLOR_BGR2HSV)], [0, 1], None, [30, 32], [0, 180, 0, 256]
    )
    h2 = cv2.calcHist(
        [cv2.cvtColor(img2_bgr, cv2.COLOR_BGR2HSV)], [0, 1], None, [30, 32], [0, 180, 0, 256]
    )
    cv2.normalize(h1, h1)
    cv2.normalize(h2, h2)
    # compareHist returns 0.0 for identical, 1.0 for completely different with BHATTACHARYYA
    dist = cv2.compareHist(h1, h2, cv2.HISTCMP_BHATTACHARYYA)
    return max(0.0, 1.0 - dist)


class HybridDetector(LocalDetector):
    """ORB + HSV histogram hybrid — works for both textured and uniform samples."""

    def __init__(self) -> None:
        self._orb = cv2.ORB_create(nfeatures=_MAX_FEATURES)
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self._cache: dict[str, np.ndarray] = {}   # path → bgr image

    def _load(self, path: str) -> np.ndarray:
        if path not in self._cache:
            img = cv2.imread(path)
            if img is None:
                raise FileNotFoundError(f"Cannot read sample: {path}")
            self._cache[path] = img
        return self._cache[path]

    def _orb_score(self, frame_bgr: np.ndarray, sample_bgr: np.ndarray) -> float:
        def desc(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, des = self._orb.detectAndCompute(gray, None)
            return des

        des1 = desc(frame_bgr)
        des2 = desc(sample_bgr)
        if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
            return 0.0
        matches = self._bf.knnMatch(des1, des2, k=2)
        good = sum(1 for pair in matches if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance)
        denom = min(len(des1), len(des2))
        return good / denom if denom > 0 else 0.0

    def _template_score(self, frame_bgr: np.ndarray, sample_bgr: np.ndarray) -> float:
        """
        Normalised cross-correlation template matching at multiple scales.
        Returns highest match score found at any scale.

        Safety: TM_CCOEFF_NORMED is undefined (NaN/Inf) for constant-colour images
        (zero std-dev). We check for that and return 0.0 in such cases.
        """
        fh, fw = frame_bgr.shape[:2]
        sh, sw = sample_bgr.shape[:2]

        # Skip template matching for images with near-zero variance (uniform colour)
        if float(np.std(sample_bgr)) < 2.0:
            return 0.0

        best = 0.0
        for scale in (1.0, 0.75, 0.5, 1.25, 1.5):
            rw, rh = int(sw * scale), int(sh * scale)
            if rw > fw or rh > fh or rw < 8 or rh < 8:
                continue
            tpl = cv2.resize(sample_bgr, (rw, rh))
            result = cv2.matchTemplate(frame_bgr, tpl, cv2.TM_CCOEFF_NORMED)
            # Guard against NaN/Inf from constant regions
            valid = result[np.isfinite(result)]
            if len(valid) == 0:
                continue
            maxv = float(valid.max())
            if maxv > best:
                best = maxv
        return max(0.0, best)

    def score(self, frame_bgr: np.ndarray, sample_paths: list[str]) -> tuple[float, str | None]:
        best_score = 0.0
        best_path: str | None = None
        for sp in sample_paths:
            try:
                sample = self._load(sp)
                orb = self._orb_score(frame_bgr, cv2.resize(sample, (frame_bgr.shape[1], frame_bgr.shape[0])))
                hist = _hist_score(frame_bgr, cv2.resize(sample, (frame_bgr.shape[1], frame_bgr.shape[0])))
                tmpl = self._template_score(frame_bgr, sample)
                combined = max(orb, hist, tmpl)
                if combined > best_score:
                    best_score = combined
                    best_path = sp
            except Exception:
                continue
        return best_score, best_path


# Default detector used by the pipeline
ORBDetector = HybridDetector   # alias for backward compatibility


def above_threshold(score: float) -> bool:
    return score >= local_prefilter_threshold()
