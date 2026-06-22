"""Anthropic multimodal provider adapter (placeholder)."""
from __future__ import annotations

from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import MultimodalRequest, MultimodalRawResponse


class AnthropicProviderAdapter(MultimodalProvider):
    """Anthropic vision provider adapter. Not yet implemented."""

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        import os
        return os.getenv("ANTHROPIC_MULTIMODAL_MODEL", "claude-opus-4-8")

    def generate(self, request: MultimodalRequest) -> MultimodalRawResponse:
        raise NotImplementedError(
            "Anthropic provider adapter is not yet implemented. "
            "Set MULTIMODAL_PROVIDER=qwen or MULTIMODAL_PROVIDER=mock."
        )
