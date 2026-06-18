"""Resolve provider name → LLMProvider instance.

Default (no args): CVComparator — pure local vision, no API key needed.

LLM_ENABLE_REAL_CALLS=false (default):
  Any LLM provider name silently falls back to CVComparator.

LLM_ENABLE_REAL_CALLS=true + LLM_PROVIDER=qwen/openai but no API key:
  Raises ValueError — explicit LLM intent with missing credentials is an
  operator error, not a silent fallback.

LLM_ENABLE_REAL_CALLS=true + key present:
  Routes to the named LLM provider.
"""
import os
from src.llm.base import LLMProvider

_LLM_PROVIDERS = {"qwen", "openai"}


def get_provider(name: str | None = None) -> LLMProvider:
    provider = name or os.getenv("LLM_PROVIDER", "cv")

    if provider == "cv":
        from src.cv.comparator import CVComparator
        return CVComparator()

    if provider == "mock":
        from src.llm.mock_provider import MockProvider
        return MockProvider()

    real_calls = os.getenv("LLM_ENABLE_REAL_CALLS", "false").lower() == "true"

    if not real_calls:
        # LLM globally disabled — silent fallback to CV
        from src.cv.comparator import CVComparator
        return CVComparator()

    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")

    if not api_key:
        if provider in _LLM_PROVIDERS:
            raise ValueError(
                f"LLM_ENABLE_REAL_CALLS=true but no API key found for provider "
                f"{provider!r}. Set DASHSCOPE_API_KEY / QWEN_API_KEY, "
                "or set LLM_PROVIDER=cv to use local CV."
            )
        from src.cv.comparator import CVComparator
        return CVComparator()

    if provider == "qwen":
        from src.llm.qwen_provider import QwenProvider
        return QwenProvider()

    if provider == "openai":
        from src.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()

    raise ValueError(f"Unknown LLM provider: {provider!r}")
