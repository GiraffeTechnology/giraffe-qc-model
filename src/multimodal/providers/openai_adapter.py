"""OpenAI multimodal provider adapter (placeholder)."""
from __future__ import annotations

from src.multimodal.errors import MultimodalConfigError
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import MultimodalRequest, MultimodalRawResponse


class OpenAIProviderAdapter(MultimodalProvider):
    """OpenAI vision provider adapter. Not yet implemented."""

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        import os
        return os.getenv("OPENAI_MULTIMODAL_MODEL", "gpt-4o")

    def generate(self, request: MultimodalRequest) -> MultimodalRawResponse:
        raise NotImplementedError(
            "OpenAI provider adapter is not yet implemented. "
            "Set MULTIMODAL_PROVIDER=qwen or MULTIMODAL_PROVIDER=mock."
        )
