# NON-PRODUCTION MOCK — simulated edge-CV inference for CI/dev. Never a real verdict source.
"""Deterministic mock CV inference used by the CPU fallback and the mock agent.

No real model or hardware is involved — this produces a plausible, structured CV
result so the whole vertical slice (and CI) runs without a GPU or a Jetson. The
output is intentionally low-confidence and flagged ``needs_human_review`` because
a mock/CPU result is evidence for a human, never a QC verdict (§16, §27).
"""
from __future__ import annotations

from typing import Optional


def mock_infer(task_type: str, input_payload: Optional[dict] = None, runner: str = "mock_edge_cv") -> dict:
    """Return a deterministic structured CV result for a task type.

    Shaped like the §12.3 upload-result payload (minus device/session identity),
    so callers can persist it directly via ``results.upload_result``.
    """
    image_uri = (input_payload or {}).get("image_uri", "mock://input")
    detections = [
        {"label": "pearl_candidate", "bbox": [120, 88, 22, 22], "confidence": 0.91},
        {"label": "petal_damage_candidate", "bbox": [330, 210, 56, 41], "confidence": 0.74},
    ]
    measurements = {
        "pearl_candidate_count": 8,
        "rhinestone_candidate_count": 12,
        "flower_core_offset_ratio": 0.08,
    }
    return {
        "result_type": "detection",
        "confidence": 0.80,
        "pass_fail_hint": "needs_human_review",
        "detections": detections,
        "measurements": measurements,
        "features": {},
        "evidence_assets": [
            {
                "asset_type": "annotated_image",
                "asset_uri": f"mock://cv-output/{runner}/annotated.jpg",
                "asset_hash": "sha256:mock",
                "width": 640,
                "height": 480,
            }
        ],
        "raw_output": {"runner": runner, "runtime_ms": 42, "source": image_uri},
    }
