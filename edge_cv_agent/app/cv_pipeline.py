# NON-PRODUCTION MOCK — the mock CV runner below simulates Jetson outcomes for CI (§14.3).
"""Mock CV pipeline + runner (§14.3).

The mock runner deterministically simulates the outcomes the PRD requires so
CI can exercise every branch without a Jetson: success, timeout, memory
failure, model missing, model-hash mismatch, partial result, invalid schema.

Selection is driven by the job's ``input_payload["mock_scenario"]`` (or the
``EDGE_AGENT_FORCE_SCENARIO`` env var), defaulting to ``success``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


class MockCVError(Exception):
    """Raised by the mock runner to simulate a runtime failure."""

    def __init__(self, error_code: str, message: str = ""):
        super().__init__(message or error_code)
        self.error_code = error_code


@dataclass
class CVOutput:
    result_type: str
    confidence: float
    pass_fail_hint: str
    detections: list
    measurements: dict
    features: dict
    evidence_assets: list
    raw_output: dict


def _success_output() -> CVOutput:
    return CVOutput(
        result_type="detection",
        confidence=0.82,
        pass_fail_hint="needs_human_review",
        detections=[
            {"label": "pearl_candidate", "bbox": [120, 88, 22, 22], "confidence": 0.91},
            {"label": "petal_damage_candidate", "bbox": [330, 210, 56, 41], "confidence": 0.74},
        ],
        measurements={
            "pearl_candidate_count": 8,
            "rhinestone_candidate_count": 12,
            "flower_core_offset_ratio": 0.08,
        },
        features={},
        evidence_assets=[
            {"asset_type": "annotated_image", "asset_uri": "storage://cv-output/annotated.jpg", "asset_hash": "sha256:mock"}
        ],
        raw_output={"runner": "mock_edge_cv", "runtime_ms": 318},
    )


def run_mock_pipeline(job: dict, scenario: Optional[str] = None) -> CVOutput:
    """Run the mock CV pipeline for a pulled job, honouring a mock scenario."""
    payload = job.get("input_payload") or {}
    scenario = scenario or payload.get("mock_scenario") or os.getenv("EDGE_AGENT_FORCE_SCENARIO") or "success"

    if scenario == "success":
        return _success_output()
    if scenario == "timeout":
        raise MockCVError("timeout", "mock inference timed out")
    if scenario == "memory_failure":
        raise MockCVError("memory_failure", "mock out-of-memory")
    if scenario == "model_missing":
        raise MockCVError("model_missing", "model artifact not found")
    if scenario == "model_hash_mismatch":
        raise MockCVError("model_hash_mismatch", "model hash does not match manifest")
    if scenario == "partial_result":
        out = _success_output()
        # Drop the required result_type to simulate a partial/invalid payload.
        out.result_type = ""
        return out
    if scenario == "invalid_schema":
        out = _success_output()
        out.pass_fail_hint = "definitely_broken"  # not an allowed hint
        return out
    return _success_output()
