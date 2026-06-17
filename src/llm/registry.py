"""Resolve provider name → LLMProvider instance."""
import os
from src.llm.base import LLMProvider


def get_provider(name: str | None = None) -> LLMProvider:
    provider = name or os.getenv("LLM_PROVIDER", "qwen")
    real_calls = os.getenv("LLM_ENABLE_REAL_CALLS", "false").lower() == "true"
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")

    if provider == "mock" or not real_calls or not api_key:
        from src.llm.mock_provider import MockProvider
        return MockProvider()

    if provider == "qwen":
        from src.llm.qwen_provider import QwenProvider
        return QwenProvider()

    if provider == "openai":
        from src.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()

    raise ValueError(f"Unknown LLM provider: {provider!r}")
