"""Mock qc-model inference (stateless per request, §3/§4).

Validates the incoming request against the shared §4 contract, then produces a
deterministic per-detection-point result. No real VLM/GPU — CI runs without
hardware. The output is **evidence, not a verdict**: the Server still recomputes
the final pass/fail (S4).

A request may carry ``mock_result`` on a detection point (``pass|fail|uncertain``)
to drive a specific outcome in tests; otherwise the result is derived
deterministically from the point code so runs are stable.
"""
from __future__ import annotations

import hashlib

from src.qc_model.jetson import constants as C
from src.qc_model.jetson.contract import InferenceRequest, InferenceResponse, PerPointResult, validate_request

_RESULT_CYCLE = [C.RESULT_PASS, C.RESULT_PASS, C.RESULT_UNCERTAIN, C.RESULT_FAIL]


def _deterministic_result(point_code: str) -> str:
    h = int(hashlib.sha256(point_code.encode("utf-8")).hexdigest(), 16)
    return _RESULT_CYCLE[h % len(_RESULT_CYCLE)]


def run_inference(payload: dict) -> dict:
    """Validate + run mock inference. Returns the §4 response dict.

    Raises ``pydantic.ValidationError`` on a malformed request (the caller maps
    that to a rejected request).
    """
    req: InferenceRequest = validate_request(payload)
    results = []
    raw_points = {dp.get("point_code"): dp for dp in payload.get("detection_points", []) if isinstance(dp, dict)}
    for dp in req.detection_points:
        forced = (raw_points.get(dp.point_code) or {}).get("mock_result")
        result = forced if forced in C.INFERENCE_RESULTS else _deterministic_result(dp.point_code)
        confidence = 0.95 if result == C.RESULT_PASS else (0.4 if result == C.RESULT_UNCERTAIN else 0.88)
        results.append(
            PerPointResult(
                point_code=dp.point_code,
                result=result,
                confidence=confidence,
                evidence=f"mock qc-model inference for {dp.point_code} ({dp.label or 'point'})",
            )
        )
    return InferenceResponse(job_id=req.job_id, per_point_results=results).model_dump()
