"""Tests for LLM abstraction layer — runs entirely in mock mode, no real API."""
import os
import pytest
from src.llm.base import LLMProvider, ImageCompareResult
from src.llm.mock_provider import MockProvider
from src.llm.openai_provider import OpenAIProvider
from src.llm.registry import get_provider


class TestMockProvider:
    def setup_method(self):
        self.p = MockProvider()

    def test_provider_name(self):
        assert self.p.provider_name == "mock"

    def test_model_name(self):
        assert self.p.model_name == "mock-v1"

    def test_compare_images_returns_result(self):
        r = self.p.compare_images(
            standard_paths=["tests/fixtures/red_square.png"],
            production_paths=["tests/fixtures/red_square_with_dot.png"],
        )
        assert isinstance(r, ImageCompareResult)

    def test_result_fields_populated(self):
        r = self.p.compare_images([], [])
        assert r.overall_result in ("pass", "needs_fix", "reject", "unknown")
        assert 0.0 <= r.similarity_score <= 1.0
        assert r.http_status == 200
        assert r.elapsed_ms >= 0
        assert isinstance(r.feedback_zh, str)
        assert isinstance(r.feedback_en, str)
        assert isinstance(r.deviations, list)

    def test_is_subclass_of_base(self):
        assert isinstance(self.p, LLMProvider)


class TestOpenAIProviderSkeleton:
    def test_raises_not_implemented(self):
        p = OpenAIProvider()
        with pytest.raises(NotImplementedError):
            p.compare_images([], [])

    def test_provider_name(self):
        assert OpenAIProvider().provider_name == "openai"


class TestRegistry:
    def test_mock_when_real_calls_disabled(self, monkeypatch):
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        p = get_provider("qwen")
        assert p.provider_name == "mock"

    def test_mock_when_no_api_key(self, monkeypatch):
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        p = get_provider("qwen")
        assert p.provider_name == "mock"

    def test_explicit_mock_provider(self, monkeypatch):
        p = get_provider("mock")
        assert p.provider_name == "mock"

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-fake")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider("nonexistent_llm")
