"""Deterministic mocked VLM provider for Phase 1 tests.

This provider returns scripted structured output so that schema, parser,
finalizer, and lifecycle behaviour can be tested without any real model.

IMPORTANT (PRD §9.2): a passing mocked test proves the engine enforces rules
and manages lifecycle. It does NOT prove real qwen3.5-vl visual accuracy.
"""
from __future__ import annotations

from src.qc_model.providers.base import (
    ProviderCaptureQuality,
    ProviderCheckpointResult,
    ProviderIncidentalFinding,
    VisionLanguageModelProvider,
    VisualInspectionRequest,
    VisualInspectionResponse,
)


class MockVLMProvider(VisionLanguageModelProvider):
    """Scriptable mock.

    Pass ``scripted`` to control per-checkpoint results, e.g.::

        MockVLMProvider(scripted={"missing_rhinestone": "fail"})

    Any checkpoint not in ``scripted`` defaults to ``default_result``.
    """

    def __init__(
        self,
        scripted: dict[str, str] | None = None,
        default_result: str = "pass",
        overall_claim: str | None = None,
        capture_acceptable: bool = True,
        capture_issues: list[str] | None = None,
        incidental: list[ProviderIncidentalFinding] | None = None,
        valid: bool = True,
        with_evidence: bool = True,
        confidence: float = 0.9,
        provider_name: str = "mock_vlm",
        model_name: str = "mock-vlm-v1",
    ) -> None:
        self._scripted = scripted or {}
        self._default_result = default_result
        self._overall_claim = overall_claim
        self._capture_acceptable = capture_acceptable
        self._capture_issues = capture_issues or []
        self._incidental = incidental or []
        self._valid = valid
        self._with_evidence = with_evidence
        self._confidence = confidence
        self._provider_name = provider_name
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def inspect(self, request: VisualInspectionRequest) -> VisualInspectionResponse:
        if not self._valid:
            return VisualInspectionResponse(
                overall_result="review_required",
                checkpoint_results=[],
                provider=self._provider_name,
                model=self._model_name,
                valid=False,
                error="mock: invalid / unparseable model output",
                raw_summary="<<not-json>>",
            )

        results: list[ProviderCheckpointResult] = []
        for point in request.detection_points:
            code = point.get("code", "")
            verdict = self._scripted.get(code, self._default_result)
            evidence = (
                f"Observed visual signal for {code} at "
                f"{point.get('target_region', 'target region')}."
                if self._with_evidence
                else ""
            )
            results.append(
                ProviderCheckpointResult(
                    code=code,
                    result=verdict,
                    visual_evidence=evidence,
                    normal_vs_defect_reasoning=(
                        "Compared against confirmed normal visual features."
                        if self._with_evidence
                        else ""
                    ),
                    pseudo_defect_analysis="No capture artifact explains the signal."
                    if self._with_evidence
                    else "",
                    confidence=self._confidence,
                    requires_human_review=(verdict == "review_required"),
                )
            )

        derived_overall = (
            self._overall_claim
            if self._overall_claim is not None
            else _claim_overall([r.result for r in results])
        )

        return VisualInspectionResponse(
            overall_result=derived_overall,
            checkpoint_results=results,
            provider=self._provider_name,
            model=self._model_name,
            confidence=self._confidence,
            incidental_findings=list(self._incidental),
            capture_quality=ProviderCaptureQuality(
                acceptable=self._capture_acceptable,
                issues=list(self._capture_issues),
            ),
            valid=True,
            raw_summary="mock structured response",
        )


def _claim_overall(results: list[str]) -> str:
    if any(r == "fail" for r in results):
        return "fail"
    if any(r == "review_required" for r in results):
        return "review_required"
    return "pass"
