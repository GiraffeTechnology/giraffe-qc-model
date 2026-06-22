"""Provider registry — selects and constructs the active multimodal provider.

Controlled by env vars:
  MULTIMODAL_PROVIDER=qwen|openai|anthropic|local_mnn|mock|cv
  MULTIMODAL_ENABLE_REAL_CALLS=false

Rules:
1. Default provider: qwen
2. If MULTIMODAL_ENABLE_REAL_CALLS=false → always return MockProvider
3. If real calls enabled but key missing → raise MultimodalConfigError
4. Never silently use fake provider in production mode
"""
from __future__ import annotations

import os

from src.multimodal.config import multimodal_enable_real_calls, multimodal_provider
from src.multimodal.errors import MultimodalConfigError
from src.multimodal.providers.base import MultimodalProvider


def get_provider(provider_name: str | None = None) -> MultimodalProvider:
    """Return the active provider instance.

    If real calls are disabled, always returns MockProvider regardless of provider_name.
    """
    from src.multimodal.providers.mock_provider import MockProvider

    name = (provider_name or multimodal_provider()).lower()

    if not multimodal_enable_real_calls():
        # Safe default for CI and local dev — never make real API calls
        return MockProvider()

    # Real calls enabled — validate and construct the requested provider
    if name == "mock":
        return MockProvider()

    if name in ("qwen", "dashscope"):
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY") or ""
        if not api_key:
            raise MultimodalConfigError(
                "MULTIMODAL_ENABLE_REAL_CALLS=true but QWEN_API_KEY / DASHSCOPE_API_KEY is not set."
            )
        from src.multimodal.providers.qwen_dashscope import QwenDashScopeProvider
        return QwenDashScopeProvider()

    if name == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise MultimodalConfigError("OPENAI_API_KEY is not set.")
        from src.multimodal.providers.openai_adapter import OpenAIProviderAdapter
        return OpenAIProviderAdapter()

    if name == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise MultimodalConfigError("ANTHROPIC_API_KEY is not set.")
        from src.multimodal.providers.anthropic_adapter import AnthropicProviderAdapter
        return AnthropicProviderAdapter()

    if name == "local_mnn":
        from src.multimodal.providers.local_mnn_stub import LocalMnnProviderAdapter
        return LocalMnnProviderAdapter()

    if name == "cv":
        # CV-only mode — no LLM calls; capability modules fall through to deterministic rules
        return MockProvider()

    raise MultimodalConfigError(
        f"Unknown MULTIMODAL_PROVIDER value: {name!r}. "
        "Supported: qwen, openai, anthropic, local_mnn, mock, cv"
    )
