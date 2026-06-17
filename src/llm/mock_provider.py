"""Deterministic mock — used when LLM_ENABLE_REAL_CALLS=false or no API key."""
from src.llm.base import LLMProvider, ImageCompareResult


class MockProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-v1"

    def compare_images(
        self,
        standard_paths: list[str],
        production_paths: list[str],
        requirements: str = "",
        notes: str = "",
    ) -> ImageCompareResult:
        return ImageCompareResult(
            overall_result="pass",
            similarity_score=0.95,
            severity="low",
            feedback_zh="[mock] 图片与标准样本高度相似，质检通过。",
            feedback_en="[mock] Production image matches standard. QC passed.",
            deviations=[],
            provider="mock",
            model="mock-v1",
            http_status=200,
            elapsed_ms=1,
            raw_summary="mock response",
        )
