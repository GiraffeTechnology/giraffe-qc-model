"""Mock inference adapter -- deterministic, no real VLM/GPU (§3/§4).

Thin ``InferenceAdapter`` wrapper around ``inference_server.infer``. Kept as a
separate module (not folded into ``inference_server.py``) so
``JetsonRunnerService`` can select an adapter uniformly without special-casing
mock mode, and so mock-mode callers of the raw ``inference_server`` functions
(pre-existing tests) keep working unchanged.
"""
from __future__ import annotations

from jetson_runner.app import inference_server
from jetson_runner.app.adapters.base import InferenceAdapter
from jetson_runner.app.admin_contract import AdminPointResult, AdminRecognitionRequest
from src.qc_model.jetson.contract import InferenceResponse


class MockInferenceAdapter(InferenceAdapter):
    """Deterministic, hash-derived results. Never touches real image content."""

    @property
    def adapter_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-deterministic"

    def is_ready(self) -> bool:
        return True

    def run_inference(self, payload: dict) -> InferenceResponse:
        return inference_server.infer(payload)

    def run_admin_recognition(
        self,
        request: AdminRecognitionRequest,
        image_paths: dict[str, str],
    ) -> list[AdminPointResult]:
        return [
            AdminPointResult(
                point_code=point.point_code,
                result="uncertain",
                confidence=0.0,
                evidence=(
                    "MOCK INFERENCE — NOT REAL QC JUDGMENT; "
                    f"CI fixture response for {point.point_code}"
                ),
                cv_status=point.cv_status,
                cv_analysis=point.cv_analysis,
            )
            for point in request.detection_points
        ]
