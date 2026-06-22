"""Tests for report generation capability."""
from __future__ import annotations

import json


def _make_custom_mock(response_json: dict):
    from src.multimodal.providers.mock_provider import MockProvider
    class CM(MockProvider):
        def generate(self, request):
            from src.multimodal.types import MultimodalRawResponse
            return MultimodalRawResponse(
                provider="mock", model="mock-v1",
                raw_text=json.dumps(response_json), raw_json=response_json,
                latency_ms=1, http_status=200,
            )
    return CM()


def _make_inspection_result(overall: str):
    from src.multimodal.types import QCInspectionResult
    return QCInspectionResult(
        overall_result=overall,
        engine="multimodal_qc",
        provider="mock",
        model_name="mock-v1",
        confidence=0.9,
        items=[],
        summary="test",
    )


def test_report_generation_pass():
    provider = _make_custom_mock({
        "report_zh": "质检报告：通过。",
        "report_en": "QC Report: Passed.",
        "executive_summary_zh": "通过",
        "executive_summary_en": "Passed",
    })
    from src.multimodal.capabilities.report_generation import generate_report
    result = _make_inspection_result("pass")
    report = generate_report(provider, result)
    assert "通过" in report.report_zh
    assert "Passed" in report.report_en


def test_report_cannot_change_overall_result():
    """Report generation must not alter the inspection result's overall_result."""
    provider = _make_custom_mock({
        "report_zh": "报告",
        "report_en": "Report",
        "executive_summary_zh": "摘要",
        "executive_summary_en": "Summary",
    })
    from src.multimodal.capabilities.report_generation import generate_report
    result = _make_inspection_result("fail")
    report = generate_report(provider, result)
    # The report was generated but the inspection result is unchanged
    assert result.overall_result == "fail"
