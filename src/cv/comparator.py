"""
Pure computer-vision QC comparator — no LLM required.

Four signals combined adaptively:
  • HSV colour histogram (Bhattacharyya)   — 38 % when no ORB texture
  • Structural similarity (NCC / pixel)    — 38 %
  • ORB keypoint matching                  — 24 % (only when texture found)
  • Per-pixel normalised diff              — baseline sanity

Defect detection runs on a morphological diff-map and can override
the similarity-based verdict even when the aggregate score is high.
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from src.llm.base import ImageCompareResult, LLMProvider

_W, _H = 320, 240           # canonical comparison resolution

# ── Decision thresholds ──────────────────────────────────────────────────────
_COLOUR_REJECT = 0.40       # HSV similarity below this → reject
_COLOUR_WARN   = 0.72
_DEFECT_NOISE  = 0.004      # blobs < 0.4 % area = noise, ignore
_DEFECT_WARN   = 0.015      # ≥ 1.5 % area → needs_fix
_DEFECT_REJECT = 0.07       # ≥ 7 %   area → reject
_SIM_PASS      = 0.86
_SIM_FIX       = 0.60


class CVComparator(LLMProvider):
    """QC image comparator using local computer vision only — drop-in LLMProvider."""

    # ── LLMProvider interface ────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "cv"

    @property
    def model_name(self) -> str:
        return "orb+hist+ncc+defect-v1"

    def compare_images(
        self,
        standard_paths: list[str],
        production_paths: list[str],
        requirements: str = "",
        notes: str = "",
    ) -> ImageCompareResult:
        t0 = time.monotonic()

        std  = self._load(standard_paths)
        prod = self._load(production_paths)

        colour         = self._colour_score(std, prod)
        struct         = self._struct_score(std, prod)
        orb, has_orb   = self._orb_score(std, prod)
        pixel          = self._pixel_score(std, prod)
        defects        = self._detect_defects(std, prod)

        # Adaptive weighted similarity
        if has_orb:
            sim = 0.25 * colour + 0.30 * struct + 0.25 * orb + 0.20 * pixel
        else:
            sim = 0.38 * colour + 0.38 * struct + 0.24 * pixel
        sim = round(float(np.clip(sim, 0.0, 1.0)), 4)

        defect_ratio = sum(d["area_ratio"] for d in defects)

        # Base verdict from similarity
        if sim >= _SIM_PASS:
            verdict, severity = "pass", "low"
        elif sim >= _SIM_FIX:
            verdict, severity = "needs_fix", "low" if sim >= 0.75 else "medium"
        else:
            verdict, severity = "reject", "high"

        # Override: colour fail
        if colour < _COLOUR_REJECT:
            verdict, severity = "reject", "high"
        # Override: defect area
        elif defect_ratio >= _DEFECT_REJECT:
            verdict, severity = "reject", "high"
        elif defect_ratio >= _DEFECT_WARN and verdict == "pass":
            verdict, severity = "needs_fix", "low"

        feedback_zh, feedback_en = self._feedback(verdict, colour, struct, defects)
        deviations = self._deviations(colour, struct, defects)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return ImageCompareResult(
            overall_result=verdict,
            similarity_score=sim,
            severity=severity,
            feedback_zh=feedback_zh,
            feedback_en=feedback_en,
            deviations=deviations,
            provider=self.provider_name,
            model=self.model_name,
            http_status=200,
            elapsed_ms=elapsed_ms,
            raw_summary=(
                f"colour={colour:.3f} struct={struct:.3f} "
                f"orb={'%.3f' % orb if has_orb else 'n/a'} "
                f"pixel={pixel:.3f} defects={len(defects)}"
            ),
        )

    # ── Signal extraction ────────────────────────────────────────────────────

    def _load(self, paths: list[str]) -> np.ndarray:
        for p in paths:
            img = cv2.imread(p)
            if img is not None:
                return img
        raise FileNotFoundError(
            f"No readable image found; tried: {paths}"
        )

    def _r(self, img: np.ndarray) -> np.ndarray:
        return cv2.resize(img, (_W, _H))

    def _colour_score(self, img1: np.ndarray, img2: np.ndarray) -> float:
        h1 = cv2.cvtColor(self._r(img1), cv2.COLOR_BGR2HSV)
        h2 = cv2.cvtColor(self._r(img2), cv2.COLOR_BGR2HSV)
        hist1 = cv2.calcHist([h1], [0, 1], None, [50, 60], [0, 180, 0, 256])
        hist2 = cv2.calcHist([h2], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist1, hist1)
        cv2.normalize(hist2, hist2)
        dist = float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_BHATTACHARYYA))
        return float(max(0.0, 1.0 - dist))

    def _struct_score(self, img1: np.ndarray, img2: np.ndarray) -> float:
        g1 = cv2.cvtColor(self._r(img1), cv2.COLOR_BGR2GRAY).astype(np.float32)
        g2 = cv2.cvtColor(self._r(img2), cv2.COLOR_BGR2GRAY).astype(np.float32)
        s1, s2 = float(np.std(g1)), float(np.std(g2))
        if s1 < 3.0 and s2 < 3.0:
            # Both nearly uniform — compare mean brightness
            return float(max(0.0, 1.0 - abs(g1.mean() - g2.mean()) / 128.0))
        if s1 < 3.0 or s2 < 3.0:
            # One uniform, one not — pixel-level grayscale diff
            return float(max(0.0, 1.0 - float(np.mean(np.abs(g1 - g2))) / 128.0))
        # Both textured — normalised cross-correlation
        corr = float(np.mean((g1 - g1.mean()) * (g2 - g2.mean())) / (s1 * s2))
        return float(np.clip((corr + 1.0) / 2.0, 0.0, 1.0))

    def _orb_score(self, img1: np.ndarray, img2: np.ndarray) -> tuple[float, bool]:
        orb = cv2.ORB_create(nfeatures=500)
        g1  = cv2.cvtColor(self._r(img1), cv2.COLOR_BGR2GRAY)
        g2  = cv2.cvtColor(self._r(img2), cv2.COLOR_BGR2GRAY)
        kp1, des1 = orb.detectAndCompute(g1, None)
        kp2, des2 = orb.detectAndCompute(g2, None)
        if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
            return 0.0, False
        bf   = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        raw  = bf.knnMatch(des1, des2, k=2)
        good = [m for m, n in raw if m.distance < 0.75 * n.distance]
        return min(1.0, len(good) / max(len(kp1), len(kp2))), True

    def _pixel_score(self, img1: np.ndarray, img2: np.ndarray) -> float:
        r1 = self._r(img1).astype(np.float32) / 255.0
        r2 = self._r(img2).astype(np.float32) / 255.0
        return float(max(0.0, 1.0 - 4.0 * float(np.mean(np.abs(r1 - r2)))))

    def _detect_defects(self, std: np.ndarray, prod: np.ndarray) -> list[dict]:
        diff   = cv2.absdiff(self._r(std), self._r(prod))
        gray   = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, th  = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
        k      = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        clean  = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k)
        cnts, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        total  = _W * _H
        result = []
        for c in cnts:
            area  = cv2.contourArea(c)
            ratio = area / total
            if ratio < _DEFECT_NOISE:
                continue
            x, y, cw, ch = cv2.boundingRect(c)
            result.append({
                "area_ratio": round(ratio, 4),
                "bbox":       [int(x), int(y), int(cw), int(ch)],
                "location":   _loc(x + cw // 2, y + ch // 2),
                "field":      "surface",
            })
        return result

    # ── Feedback & deviation builders ────────────────────────────────────────

    def _feedback(
        self, verdict: str, colour: float, struct: float, defects: list[dict]
    ) -> tuple[str, str]:
        zh_parts, en_parts = [], []
        if colour < _COLOUR_WARN:
            zh_parts.append(f"颜色偏差（色相匹配度 {colour:.0%}）")
            en_parts.append(f"colour mismatch (score {colour:.0%})")
        if struct < 0.72:
            zh_parts.append(f"结构差异（相似度 {struct:.0%}）")
            en_parts.append(f"structural difference (score {struct:.0%})")
        for d in defects:
            zh_parts.append(f"缺陷：{d['location']}，面积 {d['area_ratio']:.1%}")
            en_parts.append(f"defect at {d['location']}, area {d['area_ratio']:.1%}")

        if verdict == "pass":
            return (
                "产品与标准样本高度一致，视觉检验通过。",
                "Product matches the standard. Visual QC passed.",
            )
        if verdict == "needs_fix":
            zh = "发现轻微问题，需修正：" + "；".join(zh_parts) if zh_parts else "存在轻微偏差，建议修正。"
            en = "Minor issues, fix required: " + "; ".join(en_parts) if en_parts else "Minor deviation, fix recommended."
            return zh, en
        zh = "产品不符合标准，建议拒收：" + "；".join(zh_parts) if zh_parts else "产品质量不达标，拒收。"
        en = "Product fails QC. Reject: " + "; ".join(en_parts) if en_parts else "Product fails QC standards. Rejected."
        return zh, en

    def _deviations(
        self, colour: float, struct: float, defects: list[dict]
    ) -> list[dict]:
        out = []
        if colour < _COLOUR_WARN:
            out.append({
                "field":    "colour",
                "expected": "match standard",
                "actual":   f"similarity {colour:.0%}",
                "severity": "high" if colour < _COLOUR_REJECT else "medium",
            })
        if struct < 0.72:
            out.append({
                "field":    "structure",
                "expected": "match standard",
                "actual":   f"similarity {struct:.0%}",
                "severity": "medium",
            })
        for d in defects:
            out.append({
                "field":    d["field"],
                "expected": "no defect",
                "actual":   f"defect at {d['location']}, area {d['area_ratio']:.1%}",
                "severity": "high" if d["area_ratio"] >= _DEFECT_REJECT else "medium",
            })
        return out


def _loc(cx: int, cy: int) -> str:
    v = "top" if cy < _H // 3 else ("bottom" if cy > 2 * _H // 3 else "center")
    h = "left" if cx < _W // 3 else ("right" if cx > 2 * _W // 3 else "center")
    if v == "center" and h == "center":
        return "center"
    if v == "center":
        return h
    if h == "center":
        return v
    return f"{v}-{h}"
