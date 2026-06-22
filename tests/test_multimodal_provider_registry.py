"""Tests for provider registry — env-driven provider selection."""
from __future__ import annotations

import os
import pytest


def test_registry_returns_mock_when_real_calls_disabled(monkeypatch):
    """Registry must return MockProvider when MULTIMODAL_ENABLE_REAL_CALLS=false."""
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "false")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "qwen")

    from src.multimodal.providers.registry import get_provider
    from src.multimodal.providers.mock_provider import MockProvider

    provider = get_provider()
    assert isinstance(provider, MockProvider)


def test_registry_returns_mock_when_provider_is_mock(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "true")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "mock")

    from src.multimodal.providers.registry import get_provider
    from src.multimodal.providers.mock_provider import MockProvider

    provider = get_provider()
    assert isinstance(provider, MockProvider)


def test_registry_raises_when_qwen_key_missing(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "true")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "qwen")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    from src.multimodal.errors import MultimodalConfigError
    from src.multimodal.providers.registry import get_provider

    with pytest.raises(MultimodalConfigError, match="QWEN_API_KEY"):
        get_provider()


def test_registry_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "true")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "nonexistent_provider_xyz")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from src.multimodal.errors import MultimodalConfigError
    from src.multimodal.providers.registry import get_provider

    with pytest.raises(MultimodalConfigError, match="Unknown MULTIMODAL_PROVIDER"):
        get_provider()


def test_provider_can_switch_from_qwen_to_mock(monkeypatch):
    """Provider switching must not require changing service code."""
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "false")

    from src.multimodal.providers.registry import get_provider
    from src.multimodal.providers.mock_provider import MockProvider

    # When real calls disabled, always mock regardless of provider setting
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "qwen")
    p1 = get_provider()
    assert isinstance(p1, MockProvider)

    monkeypatch.setenv("MULTIMODAL_PROVIDER", "mock")
    p2 = get_provider()
    assert isinstance(p2, MockProvider)


def test_registry_raises_when_openai_key_missing(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "true")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from src.multimodal.errors import MultimodalConfigError
    from src.multimodal.providers.registry import get_provider

    with pytest.raises(MultimodalConfigError, match="OPENAI_API_KEY"):
        get_provider()


def test_registry_raises_when_anthropic_key_missing(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "true")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from src.multimodal.errors import MultimodalConfigError
    from src.multimodal.providers.registry import get_provider

    with pytest.raises(MultimodalConfigError, match="ANTHROPIC_API_KEY"):
        get_provider()
