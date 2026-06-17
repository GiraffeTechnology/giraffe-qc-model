"""Resolve provider name → LLMProvider instance.

Default (no args): CVComparator — pure local vision, no API key needed.
Pass "qwen" or "openai" with LLM_ENABLE_REAL_CALLS=true and an API key
to use a vision LLM as an optional enhancement.
"""
import os
from src.llm.base import LLMProvider


def get_provider(name: str | None = None) -> LLMProvider:
    provider = name or os.getenv("LLM_PROVIDER", "cv")

    if provider == "cv":
        from src.cv.comparator import CVComparator
        return CVComparator()

    if provider == "mock":
        from src.llm.mock_provider import MockProvider
        return MockProvider()

    real_calls = os.getenv("LLM_ENABLE_REAL_CALLS", "false").lower() == "true"
    api_key    = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")

    if not real_calls or not api_key:
        from src.cv.comparator import CVComparator
        return CVComparator()

    if provider == "qwen":
        from src.llm.qwen_provider import QwenProvider
        return QwenProvider()

    if provider == "openai":
        from src.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()

    raise ValueError(f"Unknown LLM provider: {provider!r}")
