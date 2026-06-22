"""Mock provider for tests and CI. Returns deterministic valid JSON."""
from __future__ import annotations

import json
import time

from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import MultimodalRequest, MultimodalRawResponse

_MOCK_MODEL = "mock-multimodal-v1"


def _mock_response_for_capability(capability: str) -> dict:
    """Return a deterministic mock JSON response for the given capability."""
    if capability == "image_quality_assessment":
        return {
            "usable": True,
            "confidence": 0.95,
            "issues": [],
            "recommended_action": "proceed",
            "reason": "Image quality is acceptable for inspection.",
        }
    if capability == "sku_match":
        return {
            "matched": True,
            "top_candidates": [
                {"sku_id": "mock_sku", "standard_id": "mock_std", "score": 0.92, "reason": "Visual match confirmed."}
            ],
            "recommended_action": "proceed",
            "confidence": 0.92,
        }
    if capability == "qc_inspection":
        return {
            "overall_result": "pass",
            "confidence": 0.90,
            "model_name": _MOCK_MODEL,
            "summary": "Mock inspection: all points pass.",
            "items": [],
        }
    if capability == "defect_grounding":
        return {"defects": []}
    if capability == "ocr_extraction":
        return {
            "detected_text": [],
            "labels": [],
            "confidence": 0.85,
            "issues": [],
        }
    if capability == "report_generation":
        return {
            "report_zh": "质检报告：检验通过。",
            "report_en": "QC Report: Inspection passed.",
            "executive_summary_zh": "通过",
            "executive_summary_en": "Passed",
        }
    return {"result": "mock", "capability": capability}


class MockProvider(MultimodalProvider):
    """Deterministic mock provider. Safe for CI; never calls any API."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return _MOCK_MODEL

    def generate(self, request: MultimodalRequest) -> MultimodalRawResponse:
        mock_json = _mock_response_for_capability(request.capability)
        raw_text = json.dumps(mock_json)
        return MultimodalRawResponse(
            provider=self.provider_name,
            model=self.model_name,
            raw_text=raw_text,
            raw_json=mock_json,
            latency_ms=1,
            http_status=200,
        )
