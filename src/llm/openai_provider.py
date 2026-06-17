"""OpenAI provider skeleton — not implemented yet, raises NotImplementedError."""
from src.llm.base import LLMProvider, ImageCompareResult


class OpenAIProvider(LLMProvider):
    """Placeholder for future OpenAI vision integration."""

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return "gpt-4o"

    def compare_images(
        self,
        standard_paths: list[str],
        production_paths: list[str],
        requirements: str = "",
        notes: str = "",
    ) -> ImageCompareResult:
        raise NotImplementedError(
            "OpenAIProvider is not yet implemented. "
            "Set LLM_PROVIDER=qwen to use the Qwen implementation."
        )
